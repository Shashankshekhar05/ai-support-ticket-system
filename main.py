"""
AI-Powered Customer Support Ticket System
==========================================

A production-ready FastAPI backend that:
  1. Accepts a customer support message (POST /ticket)
  2. Classifies its PRIORITY (low / medium / high) and CATEGORY
     (refund / delay / technical / general) using the Anthropic Claude API
     via a forced tool call (guaranteed structured output).
  3. Retrieves the most relevant FAQ(s) from a small in-memory knowledge base
     using a dependency-free TF-IDF + cosine-similarity retriever (a tiny RAG).
  4. Generates an auto-reply that is GROUNDED in the retrieved FAQ context
     using Claude.
  5. Flags the ticket for human escalation when priority == "high".
  6. Stores every processed ticket and exposes them via GET /tickets.

Design choices
--------------
* The Anthropic Python SDK is used asynchronously (AsyncAnthropic) so the
  FastAPI handlers never block the event loop.
* Classification uses a *forced* tool call (tool_choice). This guarantees the
  model returns a well-formed JSON object matching our schema instead of free
  text we'd have to parse and validate by hand.
* Retrieval uses a hand-rolled TF-IDF vectorizer with cosine similarity. No
  external vector database, no embedding service -- everything runs in-process
  using only the Python standard library. This keeps the prototype fully
  self-contained while still demonstrating real semantic-ish retrieval.
* The API key is read from the ANTHROPIC_API_KEY environment variable (never
  hard-coded). The SDK picks it up automatically.

Run:
    pip install -r requirements.txt
    set ANTHROPIC_API_KEY=sk-ant-...      # Windows (PowerShell: $env:ANTHROPIC_API_KEY="...")
    uvicorn main:app --reload

Author: Shashank Shekhar - AI Engineer 
"""

from __future__ import annotations

import math
import os
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

import anthropic
from anthropic import AsyncAnthropic
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# The model is read from the environment so it can be swapped without code
# changes, but defaults to the model specified in the assignment.
MODEL_ID: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

# How many FAQ entries to feed into the reply-generation context.
TOP_K: int = int(os.getenv("RAG_TOP_K", "2"))

# A single shared async client. The SDK reads ANTHROPIC_API_KEY from the
# environment. We do NOT pass the key explicitly so it never lives in code.
# Instantiation is deferred to startup so the app can boot even if the key is
# missing (useful for documentation / health checks), and we fail loudly only
# when an endpoint actually needs Claude.
client: Optional[AsyncAnthropic] = None


# ---------------------------------------------------------------------------
# Enums and Pydantic models  (request / response contracts)
# ---------------------------------------------------------------------------


class Priority(str, Enum):
    """Allowed priority levels for a ticket."""

    low = "low"
    medium = "medium"
    high = "high"


class Category(str, Enum):
    """Allowed support categories for a ticket."""

    refund = "refund"
    delay = "delay"
    technical = "technical"
    general = "general"


class TicketRequest(BaseModel):
    """Incoming payload for POST /ticket."""

    customer_message: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="The free-text message submitted by the customer.",
        examples=["My order #4521 was supposed to arrive 5 days ago and it still hasn't shipped."],
    )
    customer_email: Optional[str] = Field(
        default=None,
        description="Optional customer email, stored with the ticket for follow-up.",
        examples=["customer@example.com"],
    )


class RetrievedFAQ(BaseModel):
    """A single FAQ entry returned by the retriever, with its relevance score."""

    id: str
    question: str
    answer: str
    score: float = Field(..., description="Cosine similarity score in [0, 1].")


class Ticket(BaseModel):
    """A fully processed ticket. This is also the shape returned to clients."""

    id: str
    customer_message: str
    customer_email: Optional[str] = None
    priority: Priority
    category: Category
    classification_reason: str = Field(
        ..., description="Short rationale from the classifier for the chosen labels."
    )
    auto_reply: str
    escalate: bool = Field(
        ..., description="True when the ticket should be routed to a human agent."
    )
    retrieved_faqs: List[RetrievedFAQ]
    created_at: str = Field(..., description="UTC ISO-8601 timestamp.")


class TicketListResponse(BaseModel):
    """Response shape for GET /tickets."""

    count: int
    tickets: List[Ticket]


# ---------------------------------------------------------------------------
# Knowledge base (RAG source)  --  small in-memory set of sample FAQs
# ---------------------------------------------------------------------------

# Each FAQ carries an optional "keywords" field of synonyms/common phrasings.
# These are indexed alongside the question and answer so the retriever still
# matches paraphrased queries (e.g. "money back" -> refund, "package" -> order)
# without needing dense embeddings. This is a common, pragmatic pattern for
# keyword/TF-IDF retrieval over a small curated knowledge base.
KNOWLEDGE_BASE: List[Dict[str, str]] = [
    {
        "id": "faq-refund",
        "question": "How do I request a refund and how long does it take?",
        "answer": (
            "You can request a refund within 30 days of purchase from the "
            "Orders page by selecting the order and clicking 'Request Refund'. "
            "Approved refunds are returned to the original payment method "
            "within 5-7 business days."
        ),
        "keywords": (
            "refund money back return returns reimburse reimbursement cancel "
            "cancellation broken damaged defective faulty charge charged "
            "money returned my money"
        ),
    },
    {
        "id": "faq-delivery-delay",
        "question": "My order is delayed or hasn't arrived. What should I do?",
        "answer": (
            "Most orders ship within 2 business days and arrive within 5-7 days. "
            "If your order is past the estimated delivery date, you can track it "
            "from the Orders page. Delays beyond 10 days qualify for a free "
            "reshipment or a full refund."
        ),
        "keywords": (
            "delay delayed late package parcel shipment shipping not arrived "
            "hasn't arrived missing lost where is my order stuck overdue "
            "still not here waiting reshipment"
        ),
    },
    {
        "id": "faq-login-technical",
        "question": "I can't log in or the app keeps crashing. How do I fix it?",
        "answer": (
            "For login issues, reset your password using 'Forgot Password'. If "
            "the app crashes, update to the latest version and clear the app "
            "cache. If problems persist, send us your device model and a "
            "screenshot of the error so engineering can investigate."
        ),
        "keywords": (
            "login log in sign in password crash crashing crashed bug error "
            "broken app website not working freezing frozen technical issue "
            "won't open glitch"
        ),
    },
    {
        "id": "faq-order-tracking",
        "question": "How do I track my order or change the shipping address?",
        "answer": (
            "Open the Orders page and click 'Track' next to your order for live "
            "carrier updates. Shipping addresses can be edited only before the "
            "order is marked 'Shipped'; after that, contact support to reroute."
        ),
        "keywords": (
            "track tracking trace status where order shipping address change "
            "update address reroute carrier delivery location"
        ),
    },
    {
        "id": "faq-account-billing",
        "question": "How do I update my billing details or download an invoice?",
        "answer": (
            "Billing details and saved payment methods are managed under "
            "Settings > Billing. Invoices for every completed order can be "
            "downloaded as PDF from the Orders page under 'Invoice'."
        ),
        "keywords": (
            "billing invoice receipt payment method card credit card update "
            "details account settings charge statement download pdf"
        ),
    },
    {
        "id": "faq-business-hours",
        "question": "What are your support hours and how fast will I get a reply?",
        "answer": (
            "Our support team is available Monday-Friday, 9am-6pm IST. "
            "Standard tickets are answered within 24 hours; high-priority issues "
            "are escalated to a live agent immediately."
        ),
        "keywords": (
            "support hours contact reply response time when open availability "
            "agent human talk speak help desk how long wait"
        ),
    },
]


# ---------------------------------------------------------------------------
# RAG retriever  --  pure-Python TF-IDF + cosine similarity (no vector DB)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# A small English stop-word list so common words don't dominate the vectors.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "is", "are", "was", "were", "to", "of",
    "in", "on", "for", "my", "i", "it", "you", "your", "how", "do", "does",
    "can", "with", "this", "that", "be", "will", "at", "as", "if", "me",
}


def _tokenize(text: str) -> List[str]:
    """Lowercase, split on non-alphanumerics, and drop stop words."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


class TfidfRetriever:
    """A minimal TF-IDF retriever with cosine similarity.

    Documents are represented as sparse term -> weight dictionaries. We compute
    IDF once at construction time, vectorize each document, then score an
    incoming query by cosine similarity against every document vector.
    """

    def __init__(self, documents: List[Dict[str, str]]):
        if not documents:
            raise ValueError("TfidfRetriever requires at least one document.")
        self.documents = documents
        # Index over question + answer + keyword tags for richer matching.
        # The keyword tags let the retriever match paraphrased queries whose
        # vocabulary differs from the FAQ prose.
        self._doc_tokens = [
            _tokenize(f"{d['question']} {d['answer']} {d.get('keywords', '')}")
            for d in documents
        ]
        self._n_docs = len(documents)

        # Document frequency: how many docs each term appears in.
        self._df: Counter = Counter()
        for tokens in self._doc_tokens:
            for term in set(tokens):
                self._df[term] += 1

        # Pre-compute each document's TF-IDF vector.
        self._doc_vectors = [self._vectorize(tokens) for tokens in self._doc_tokens]

    def _idf(self, term: str) -> float:
        """Smoothed inverse document frequency."""
        return math.log((1 + self._n_docs) / (1 + self._df.get(term, 0))) + 1.0

    def _vectorize(self, tokens: List[str]) -> Dict[str, float]:
        """Convert a token list into a sparse TF-IDF vector."""
        if not tokens:
            return {}
        counts = Counter(tokens)
        length = len(tokens)
        return {term: (count / length) * self._idf(term) for term, count in counts.items()}

    @staticmethod
    def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
        """Cosine similarity between two sparse vectors."""
        if not a or not b:
            return 0.0
        common = a.keys() & b.keys()
        dot = sum(a[t] * b[t] for t in common)
        norm_a = math.sqrt(sum(v * v for v in a.values()))
        norm_b = math.sqrt(sum(v * v for v in b.values()))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    def retrieve(self, query: str, top_k: int = TOP_K) -> List[RetrievedFAQ]:
        """Return the top_k most relevant FAQs for a query, highest score first."""
        query_vec = self._vectorize(_tokenize(query))
        scored = [
            (self._cosine(query_vec, doc_vec), doc)
            for doc_vec, doc in zip(self._doc_vectors, self.documents)
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            RetrievedFAQ(
                id=doc["id"],
                question=doc["question"],
                answer=doc["answer"],
                score=round(score, 4),
            )
            for score, doc in scored[:top_k]
        ]


# Build the retriever once at import time -- it is stateless and reusable.
retriever = TfidfRetriever(KNOWLEDGE_BASE)


# ---------------------------------------------------------------------------
# In-memory ticket store  (a real deployment would use a database)
# ---------------------------------------------------------------------------

_tickets: Dict[str, Ticket] = {}


# ---------------------------------------------------------------------------
# Claude prompts & tool schema
# ---------------------------------------------------------------------------

CLASSIFY_SYSTEM = (
    "You are a precise customer-support triage assistant for an e-commerce "
    "company. Given a single customer message, classify it.\n\n"
    "PRIORITY rules:\n"
    "  - high: the customer is blocked, angry, reports a failed payment, a "
    "lost/very late order, a security/account-access problem, or explicitly "
    "demands escalation. Anything time-sensitive or money-at-risk.\n"
    "  - medium: a real problem that is not urgent (a question about a refund "
    "status, a minor bug, a delayed-but-tracked order).\n"
    "  - low: general questions, feedback, or informational requests.\n\n"
    "CATEGORY rules:\n"
    "  - refund: anything about getting money back, returns, or cancellations.\n"
    "  - delay: shipping delays, missing/late deliveries, tracking problems.\n"
    "  - technical: app/website bugs, login issues, crashes, errors.\n"
    "  - general: everything else (billing questions, hours, how-to, feedback).\n\n"
    "Always call the classify_ticket tool with your decision."
)

CLASSIFY_TOOL = {
    "name": "classify_ticket",
    "description": "Record the priority and category classification for a support ticket.",
    "input_schema": {
        "type": "object",
        "properties": {
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "The urgency level of the ticket.",
            },
            "category": {
                "type": "string",
                "enum": ["refund", "delay", "technical", "general"],
                "description": "The topic category of the ticket.",
            },
            "reason": {
                "type": "string",
                "description": "A one-sentence justification for the chosen priority and category.",
            },
        },
        "required": ["priority", "category", "reason"],
        "additionalProperties": False,
    },
}

REPLY_SYSTEM = (
    "You are a friendly, concise customer-support agent for an e-commerce "
    "company. Write a helpful reply to the customer's message.\n\n"
    "Rules:\n"
    "  - Ground your answer ONLY in the provided FAQ context. Do not invent "
    "policies, timelines, or features that are not in the context.\n"
    "  - If the FAQ context does not fully answer the question, acknowledge "
    "that and tell the customer a human agent will follow up.\n"
    "  - Be warm and professional. Keep it under 120 words. Do not include a "
    "subject line or email headers -- just the message body."
)


# ---------------------------------------------------------------------------
# Claude-backed helper functions
# ---------------------------------------------------------------------------


def _require_client() -> AsyncAnthropic:
    """Return the active Anthropic client or raise a clear 503 if unconfigured."""
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Anthropic client is not configured. Set the ANTHROPIC_API_KEY "
                "environment variable and restart the server."
            ),
        )
    return client


async def classify_ticket(message: str) -> Dict[str, str]:
    """Classify a customer message using a forced Claude tool call.

    Returns a dict with 'priority', 'category', and 'reason'.
    """
    ac = _require_client()
    response = await ac.messages.create(
        model=MODEL_ID,
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": CLASSIFY_SYSTEM,
                # Cache the stable system prompt to cut cost on repeat calls.
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[CLASSIFY_TOOL],
        # Force the model to emit a classify_ticket tool call => structured output.
        tool_choice={"type": "tool", "name": "classify_ticket"},
        messages=[{"role": "user", "content": message}],
    )

    # With a forced tool call, the response contains a tool_use block we trust.
    for block in response.content:
        if block.type == "tool_use" and block.name == "classify_ticket":
            data = block.input
            # Defensive validation against the enum contract.
            priority = data.get("priority")
            category = data.get("category")
            if priority not in Priority.__members__ or category not in Category.__members__:
                raise ValueError(f"Classifier returned invalid labels: {data!r}")
            return {
                "priority": priority,
                "category": category,
                "reason": data.get("reason", "").strip() or "No rationale provided.",
            }

    raise ValueError("Classifier did not return a classify_ticket tool call.")


async def generate_reply(message: str, faqs: List[RetrievedFAQ]) -> str:
    """Generate an auto-reply grounded in the retrieved FAQ context."""
    ac = _require_client()

    # Assemble the retrieved FAQs into a single grounded context block.
    if faqs:
        context = "\n\n".join(
            f"FAQ [{f.id}] (relevance {f.score}):\nQ: {f.question}\nA: {f.answer}"
            for f in faqs
        )
    else:
        context = "(No relevant FAQ entries were found.)"

    user_content = (
        f"Customer message:\n\"\"\"\n{message}\n\"\"\"\n\n"
        f"Relevant FAQ context to ground your reply:\n{context}\n\n"
        "Write the reply now."
    )

    response = await ac.messages.create(
        model=MODEL_ID,
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": REPLY_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    )

    reply = "".join(block.text for block in response.content if block.type == "text").strip()
    if not reply:
        raise ValueError("Reply generation returned empty text.")
    return reply


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AI-Powered Customer Support Ticket System",
    description=(
        "Classifies, retrieves context for, and auto-replies to customer "
        "support tickets using the Anthropic Claude API."
    ),
    version="1.0.0",
)


@app.on_event("startup")
async def _startup() -> None:
    """Initialise the Anthropic client if an API key is present."""
    global client
    if os.getenv("ANTHROPIC_API_KEY"):
        client = AsyncAnthropic()  # reads ANTHROPIC_API_KEY from the environment
    else:
        # Leave client as None; endpoints will return a clear 503 until set.
        client = None


@app.get("/", tags=["health"])
async def root() -> Dict[str, object]:
    """Basic health/info endpoint."""
    return {
        "service": "AI-Powered Customer Support Ticket System",
        "model": MODEL_ID,
        "anthropic_configured": client is not None,
        "knowledge_base_size": len(KNOWLEDGE_BASE),
        "tickets_processed": len(_tickets),
    }


@app.post(
    "/ticket",
    response_model=Ticket,
    status_code=status.HTTP_201_CREATED,
    tags=["tickets"],
    summary="Submit a customer message; get classification, RAG reply, and escalation flag.",
)
async def create_ticket(payload: TicketRequest) -> Ticket:
    """Process a single customer support message end-to-end.

    Pipeline: classify -> retrieve FAQs -> generate grounded reply -> store.
    """
    message = payload.customer_message.strip()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="customer_message must not be empty.",
        )

    try:
        # 1. Classify priority + category via Claude (forced tool call).
        classification = await classify_ticket(message)

        # 2. Retrieve the most relevant FAQ entries (RAG).
        faqs = retriever.retrieve(message, top_k=TOP_K)

        # 3. Generate an auto-reply grounded in the retrieved context.
        auto_reply = await generate_reply(message, faqs)

    except anthropic.APIStatusError as exc:
        # Surface a clean error for upstream API issues (rate limits, 5xx, etc.).
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Anthropic API error ({exc.status_code}): {exc.message}",
        ) from exc
    except anthropic.APIConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Could not reach the Anthropic API. Check network connectivity.",
        ) from exc
    except ValueError as exc:
        # Our own validation failures (bad labels, empty reply, etc.).
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Model produced an unexpected result: {exc}",
        ) from exc

    priority = Priority(classification["priority"])

    ticket = Ticket(
        id=str(uuid.uuid4()),
        customer_message=message,
        customer_email=payload.customer_email,
        priority=priority,
        category=Category(classification["category"]),
        classification_reason=classification["reason"],
        auto_reply=auto_reply,
        # 4. Escalate to a human whenever priority is high.
        escalate=(priority == Priority.high),
        retrieved_faqs=faqs,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    # 5. Persist the processed ticket.
    _tickets[ticket.id] = ticket
    return ticket


@app.get(
    "/tickets",
    response_model=TicketListResponse,
    tags=["tickets"],
    summary="List all processed tickets.",
)
async def list_tickets() -> TicketListResponse:
    """Return every processed ticket, newest first."""
    tickets = sorted(_tickets.values(), key=lambda t: t.created_at, reverse=True)
    return TicketListResponse(count=len(tickets), tickets=tickets)


@app.get(
    "/tickets/{ticket_id}",
    response_model=Ticket,
    tags=["tickets"],
    summary="Fetch a single ticket by id.",
)
async def get_ticket(ticket_id: str) -> Ticket:
    """Return one ticket by id, or 404 if it does not exist."""
    ticket = _tickets.get(ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No ticket found with id {ticket_id!r}.",
        )
    return ticket


# Allow `python main.py` to run the server directly for convenience.
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
