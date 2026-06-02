# 🎫 AI-Powered Customer Support Ticket System

An async **FastAPI** backend that turns a raw customer message into a triaged,
auto-answered support ticket using the **Anthropic Claude API**. It classifies
priority and category, retrieves relevant FAQs with a lightweight in-memory RAG
(TF-IDF + cosine similarity — no external vector DB), generates a reply grounded
in that context, and flags high-priority tickets for human escalation.

---

## ✨ Features

- **Priority classification** — `low` / `medium` / `high`
- **Category classification** — `refund` / `delay` / `technical` / `general`
- **RAG retrieval** over a 6-entry in-memory FAQ knowledge base using pure-Python
  TF-IDF + cosine similarity (zero vector-DB dependencies)
- **Grounded auto-reply** generation via Claude, constrained to the retrieved FAQ context
- **Automatic human escalation** flag when `priority == "high"`
- **Persistent ticket listing** via `GET /tickets`
- Fully **async**, typed with **Pydantic v2**, with structured **error handling**
- Structured classification via **forced tool calls** (guaranteed valid JSON)

---

## 🏗️ Architecture

```
   Customer message
          │  POST /ticket
          ▼
   ┌──────────────────────────────────────────────┐
   │              FastAPI service (async)           │
   │                                                │
   │  1. Claude classifier ──► priority + category  │ ──► Claude API
   │  2. TF-IDF RAG retriever ──► top-K FAQs         │     (claude-sonnet)
   │  3. Claude reply generator (grounded in FAQs)  │ ──► Claude API
   │  4. escalate = (priority == "high")            │
   │  5. store ticket  ──►  GET /tickets             │
   └──────────────────────────────────────────────┘
          │                         │
          ▼ (if high)               ▼
   Human-agent queue          Ticket store
```

See [`PART5_ARCHITECTURE_DIAGRAM.md`](PART5_ARCHITECTURE_DIAGRAM.md) for a full
draw.io / Excalidraw build guide.

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Web framework | FastAPI (async) |
| Server | Uvicorn (ASGI) |
| LLM | Anthropic Claude — `claude-sonnet-4-20250514` |
| LLM SDK | `anthropic` (official Python SDK, `AsyncAnthropic`) |
| Validation | Pydantic v2 |
| Retrieval (RAG) | Pure-Python TF-IDF + cosine similarity (stdlib only) |
| Storage | In-memory dict (swap for Postgres in production) |
| Language | Python 3.10+ |

---

## 🚀 Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set your API key

The Anthropic SDK reads the key from the `ANTHROPIC_API_KEY` environment variable.

**Windows (PowerShell):**
```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-your-key-here"
```

**Windows (cmd):**
```cmd
set ANTHROPIC_API_KEY=sk-ant-your-key-here
```

**macOS / Linux:**
```bash
export ANTHROPIC_API_KEY="sk-ant-your-key-here"
```

> Optional: copy `.env.example` to `.env` for reference. You can also override
> `ANTHROPIC_MODEL` and `RAG_TOP_K` via environment variables.

### 3. Run the server

```bash
uvicorn main:app --reload
```

The API is now live at **http://localhost:8000**.
Interactive docs (Swagger UI): **http://localhost:8000/docs**

---

## 📡 API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET`  | `/` | Health/info: model, KB size, tickets processed |
| `POST` | `/ticket` | Process a customer message → classified, answered ticket |
| `GET`  | `/tickets` | List all processed tickets (newest first) |
| `GET`  | `/tickets/{ticket_id}` | Fetch a single ticket by id |

---

### `POST /ticket`

Submit a customer message. Returns the fully processed ticket.

**Request**

```bash
curl -X POST http://localhost:8000/ticket \
  -H "Content-Type: application/json" \
  -d '{
    "customer_message": "My order #4521 was supposed to arrive 5 days ago and it still has not shipped. I need it urgently!",
    "customer_email": "jordan@example.com"
  }'
```

**Response `201 Created`**

```json
{
  "id": "0f9c2c1e-4d3a-4f8b-9c2a-1b7e6f5a2d10",
  "customer_message": "My order #4521 was supposed to arrive 5 days ago and it still has not shipped. I need it urgently!",
  "customer_email": "jordan@example.com",
  "priority": "high",
  "category": "delay",
  "classification_reason": "The customer reports a significantly late, unshipped order and expresses urgency, which is time-sensitive.",
  "auto_reply": "I'm sorry your order #4521 hasn't shipped yet — I understand that's frustrating when you need it urgently. Most orders ship within 2 business days and arrive within 5–7 days, and you can follow live updates from the Orders page using 'Track'. Because this is past the expected window, I'm escalating it to a live agent right now who can arrange a free reshipment or a full refund. You'll hear from us shortly.",
  "escalate": true,
  "retrieved_faqs": [
    {
      "id": "faq-delivery-delay",
      "question": "My order is delayed or hasn't arrived. What should I do?",
      "answer": "Most orders ship within 2 business days and arrive within 5-7 days. If your order is past the estimated delivery date, you can track it from the Orders page. Delays beyond 10 days qualify for a free reshipment or a full refund.",
      "score": 0.4127
    },
    {
      "id": "faq-order-tracking",
      "question": "How do I track my order or change the shipping address?",
      "answer": "Open the Orders page and click 'Track' next to your order for live carrier updates. Shipping addresses can be edited only before the order is marked 'Shipped'; after that, contact support to reroute.",
      "score": 0.2013
    }
  ],
  "created_at": "2026-06-01T10:32:11.482913+00:00"
}
```

---

### `GET /tickets`

List every processed ticket.

**Request**

```bash
curl http://localhost:8000/tickets
```

**Response `200 OK`**

```json
{
  "count": 1,
  "tickets": [
    {
      "id": "0f9c2c1e-4d3a-4f8b-9c2a-1b7e6f5a2d10",
      "customer_message": "My order #4521 was supposed to arrive 5 days ago ...",
      "customer_email": "jordan@example.com",
      "priority": "high",
      "category": "delay",
      "classification_reason": "The customer reports a significantly late, unshipped order ...",
      "auto_reply": "I'm sorry your order #4521 hasn't shipped yet ...",
      "escalate": true,
      "retrieved_faqs": [ { "id": "faq-delivery-delay", "question": "...", "answer": "...", "score": 0.4127 } ],
      "created_at": "2026-06-01T10:32:11.482913+00:00"
    }
  ]
}
```

---

### `GET /tickets/{ticket_id}`

Fetch a single ticket.

**Request**

```bash
curl http://localhost:8000/tickets/0f9c2c1e-4d3a-4f8b-9c2a-1b7e6f5a2d10
```

**Response `200 OK`** — the same `Ticket` object shown above.
Returns `404 Not Found` if the id does not exist.

---

### `GET /` (health)

```bash
curl http://localhost:8000/
```

```json
{
  "service": "AI-Powered Customer Support Ticket System",
  "model": "claude-sonnet-4-20250514",
  "anthropic_configured": true,
  "knowledge_base_size": 6,
  "tickets_processed": 1
}
```

---

## ⚠️ Error Responses

| Status | When |
|---|---|
| `422 Unprocessable Entity` | Empty/invalid `customer_message` (Pydantic validation) |
| `404 Not Found` | Ticket id does not exist |
| `502 Bad Gateway` | Anthropic API error or unexpected model output |
| `503 Service Unavailable` | `ANTHROPIC_API_KEY` not configured |
| `504 Gateway Timeout` | Could not reach the Anthropic API |

---

## 🧠 How It Works (per ticket)

1. **Classify** — A *forced* Claude tool call returns `{priority, category, reason}`
   as guaranteed-valid JSON.
2. **Retrieve** — The TF-IDF retriever scores the message against all FAQ entries
   by cosine similarity and returns the top-K.
3. **Generate** — Claude writes a reply constrained to the retrieved FAQ context
   (it won't invent policies; it defers to a human when context is insufficient).
4. **Escalate** — `escalate` is set to `true` whenever `priority == "high"`.
5. **Store** — The ticket is saved and exposed via `GET /tickets`.

---

## 👤 Author

**Shashank Shekhar** — AI Engineer
