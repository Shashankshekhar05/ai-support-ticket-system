# Part 3 — Recommendation Report

**AI-Powered Customer Support Automation System**
*Prepared by: Shashank Shekhar — AI Engineer

---

## 1. Recommended Architecture

The system is a **single stateless FastAPI service** that orchestrates three
steps per ticket — classify, retrieve, reply — against the Claude API and a
lightweight in-process retriever. This keeps the moving parts minimal while
remaining horizontally scalable.

### 1.1 Text-based architecture diagram

```
                        ┌──────────────────────────────────────────────┐
                        │                Clients                        │
                        │  Web widget · Mobile app · Email · Zendesk    │
                        └───────────────────────┬──────────────────────┘
                                                 │ HTTPS (POST /ticket)
                                                 ▼
                ┌────────────────────────────────────────────────────────┐
                │                 FastAPI Service (async)                  │
                │                                                          │
                │   POST /ticket ─┐                                        │
                │                 ▼                                        │
                │        ┌──────────────────┐    forced tool call         │
                │        │  1. Classifier   │ ─────────────────────────►  │ ──► Claude API
                │        │ priority+category│ ◄─────────────────────────  │ ◄── (claude-sonnet)
                │        └────────┬─────────┘    {priority, category}     │
                │                 ▼                                        │
                │        ┌──────────────────┐                             │
                │        │ 2. RAG Retriever │  TF-IDF + cosine            │
                │        │  (in-memory FAQ) │  (no external vector DB)    │
                │        └────────┬─────────┘                             │
                │                 ▼ top-K FAQs                            │
                │        ┌──────────────────┐    grounded prompt          │
                │        │ 3. Reply Gen     │ ─────────────────────────►  │ ──► Claude API
                │        │  (grounded)      │ ◄─────────────────────────  │ ◄── (claude-sonnet)
                │        └────────┬─────────┘    reply text               │
                │                 ▼                                        │
                │        ┌──────────────────┐                             │
                │        │ 4. Escalation    │  escalate = (priority=high) │
                │        └────────┬─────────┘                             │
                │                 ▼                                        │
                │        ┌──────────────────┐                             │
                │        │ 5. Ticket Store  │  (in-memory now;            │
                │        │  GET /tickets    │   Postgres in prod)         │
                │        └──────────────────┘                             │
                └────────────────────────────────────────────────────────┘
                                 │                         │
                  high priority  │                         │ all tickets
                                 ▼                         ▼
                        ┌─────────────────┐       ┌──────────────────┐
                        │  Human agent    │       │  Analytics / CRM │
                        │  queue (alert)  │       │  dashboards      │
                        └─────────────────┘       └──────────────────┘
```

### 1.2 Why this shape

- **Stateless API** → trivially horizontally scalable behind a load balancer.
- **Two Claude calls per ticket** (classify + reply), one cheap local retrieval.
- **RAG grounds the reply** in approved FAQ text, sharply reducing hallucinated
  policies.
- **Escalation is deterministic** (`priority == high`), so the safety-critical
  routing decision never depends on free-text parsing.

---

## 2. Why Claude Was Selected Over GPT-4o and Gemini

| Criterion | Why Claude wins for support automation |
|---|---|
| **Grounding fidelity** | Claude is exceptionally good at staying inside the provided FAQ context and saying "a human will follow up" when the context is insufficient — the single most important property for a support bot (avoids confidently wrong policy answers). |
| **Instruction / tone following** | Brand-voice and "under 120 words, no email headers" style rules are followed reliably, reducing post-processing. |
| **Structured tool use** | Forced tool calls give *guaranteed* JSON for the priority/category labels, so the escalation logic is rock-solid. |
| **Long-context RAG** | 200K–1M context handles large knowledge bases without aggressive chunking. |
| **Multi-cloud** | Available first-party and via AWS Bedrock, GCP Vertex, and Azure Foundry — no single-cloud lock-in. |
| **Prompt caching** | Stable system prompt + FAQ context can be cached for up to ~90% input-cost savings on repeat traffic. |

**GPT-4o** is excellent and slightly cheaper on output, and unbeatable for
*real-time voice* — but voice is irrelevant for text tickets, and its grounding
discipline is marginally behind Claude's for policy-bound replies. **Gemini 1.5
Pro** offers the largest context and best value inside GCP, but its ecosystem is
less mature and its strongest advantages (video, 2M context) aren't needed here.

For a **text, policy-grounded, tone-sensitive triage-and-reply** workload, Claude
is the best-fit default.

---

## 3. Estimated Monthly Infrastructure Cost (1,000 tickets/day)

**Volume:** 1,000 tickets/day ≈ **30,000 tickets/month**. Each ticket makes
**2 Claude calls** (classification + reply).

### 3.1 Token assumptions (conservative)

| Call | Input tokens | Output tokens |
|---|---|---|
| Classification | ~600 (system + message) | ~80 |
| Reply generation | ~900 (system + message + FAQ context) | ~180 |
| **Per ticket total** | **~1,500 in** | **~260 out** |

Monthly totals: **~45M input tokens**, **~7.8M output tokens**.

### 3.2 Claude (Sonnet) token cost — without caching

- Input: 45M × $3.00 / 1M ≈ **$135**
- Output: 7.8M × $15.00 / 1M ≈ **$117**
- **LLM subtotal ≈ $252 / month**

### 3.3 With prompt caching (stable system prompt + FAQ context)

The bulk of the input (system prompts + FAQ context) is identical across tickets
and is cache-eligible. Realistically ~60% of input tokens become cache reads at
~0.1× price:

- Cached input savings bring **input cost down to ~$60–$80**
- **LLM subtotal with caching ≈ $180–$200 / month**

### 3.4 Hosting & supporting infra

| Item | Estimate / month |
|---|---|
| Compute (2 small containers / app service, e.g. AWS Fargate or a small VM) | $30–$60 |
| Managed Postgres (small instance, for ticket storage in prod) | $15–$30 |
| Load balancer + logging/monitoring | $20–$40 |
| **Infra subtotal** | **~$65–$130 / month** |

### 3.5 Total estimated monthly cost (small scale)

> **≈ $250–$380 / month** all-in for 1,000 tickets/day, dominated by LLM tokens.
> Prompt caching and using a cheaper model tier for the *classification* step
> (e.g. Haiku) can push this toward the low end.

---

## 4. Risks and Limitations

| Risk | Mitigation |
|---|---|
| **Hallucinated policies** — model invents a refund window not in the FAQ. | RAG grounding + explicit "only use provided context" system rule + human escalation for low-confidence/high-priority cases. |
| **Misclassification** — an urgent ticket labeled low. | Conservative classifier rubric biased toward escalation; periodic human audit of a sample; add a confidence threshold. |
| **Retrieval miss** — TF-IDF fails on paraphrased/synonym-heavy queries. | Upgrade to embedding-based retrieval (e.g. a managed vector store) as the KB grows; expand the FAQ set. |
| **API outage / rate limits** | SDK auto-retry with backoff; circuit-breaker + graceful "a human will respond" fallback; multi-cloud failover via Bedrock/Vertex. |
| **Cost spikes** under traffic bursts | Prompt caching, batch API for non-urgent tickets, per-tenant rate limiting, cheaper model for classification. |
| **PII / data privacy** | Don't log raw messages with secrets; encrypt the ticket store; honor GDPR/CCPA retention; redact before persistence. |
| **In-memory store loses data on restart** | Prototype-only; production uses a durable database (Postgres). |
| **Prompt injection** in customer messages | Treat customer text as untrusted data, not instructions; keep system rules in the system prompt; never let message text alter tool/escalation logic. |

---

## 5. Scaling to 10,000 Tickets/Day in Production

10,000 tickets/day ≈ **300,000/month**, ~7 tickets/minute average with higher
bursts. The architecture scales cleanly with targeted upgrades:

1. **Stateless horizontal scale** — Run the FastAPI service as multiple
   replicas behind a load balancer (Kubernetes / ECS / Cloud Run). Each replica
   is identical; scale out on CPU/request metrics.

2. **Durable, queryable storage** — Replace the in-memory dict with **Postgres**
   (or DynamoDB). Index by status/priority/created_at for agent dashboards.

3. **Asynchronous processing** — Put incoming tickets on a **queue**
   (SQS / RabbitMQ / Redis) and process with worker pools. The HTTP endpoint
   returns immediately with a ticket id; reply generation happens async. This
   smooths bursts and decouples ingestion from LLM latency.

4. **Cost & latency optimization at volume**
   - **Prompt caching** on the stable system prompt + FAQ context (big win at
     300K tickets/month).
   - Use a **cheaper/faster model** (e.g. Haiku) for the *classification* step
     and reserve Sonnet for reply generation.
   - **Batch API** (50% cheaper) for non-time-sensitive tickets.

5. **Better retrieval** — Swap the TF-IDF retriever for **embedding-based
   semantic search** backed by a managed vector store (pgvector, Pinecone, etc.)
   as the knowledge base grows past a few dozen entries. Add reranking.

6. **Reliability & observability**
   - SDK retry/backoff + circuit breakers around the Claude API.
   - Centralized logging, tracing, and per-step latency/cost metrics.
   - Multi-region / multi-cloud (Bedrock/Vertex) failover for the model.

7. **Human-in-the-loop at scale** — Route every `escalate: true` ticket to a
   live-agent queue with real-time alerts; sample non-escalated tickets for QA
   to continuously tune the classifier rubric and FAQ coverage.

With these changes the same core design comfortably handles 10,000+ tickets/day,
with cost scaling roughly linearly in tokens (and sub-linearly with caching).
