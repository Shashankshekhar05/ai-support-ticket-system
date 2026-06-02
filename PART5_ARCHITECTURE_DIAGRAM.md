# Part 5 — Architecture Diagram Description

**A build guide for drawing the workflow in draw.io or Excalidraw**
*Author: Shashank Shekhar — AI Engineer 

This document describes, node by node, the diagram to draw. Follow the
**flow**, **shapes**, **labels**, and **colors** sections so the result is clean
and presentation-ready.

---

## 1. The Flow (left → right, top → bottom)

```
Customer message → FastAPI → Claude Classifier → RAG Retrieval
        → Claude Reply Generator → Response (+ escalation flag if high priority)
```

---

## 2. Nodes to Draw (in order)

Draw these as connected boxes. Each row below = one shape.

| # | Shape | Label (title) | Sub-text inside the box |
|---|---|---|---|
| 1 | Rounded rectangle (start) | **Customer Message** | "Free-text support message (web / app / email)" |
| 2 | Rectangle | **FastAPI Service** `POST /ticket` | "Async API gateway — orchestrates the pipeline" |
| 3 | Rectangle (LLM) | **Claude Classifier** | "Forced tool call → `{priority, category, reason}`" |
| 4 | Cylinder/database + box | **RAG Retrieval** | "TF-IDF + cosine similarity over in-memory FAQ KB → top-K FAQs" |
| 5 | Rectangle (LLM) | **Claude Reply Generator** | "Generates reply grounded in retrieved FAQ context" |
| 6 | Decision diamond | **Priority == high?** | (branch point) |
| 7 | Rounded rectangle (end) | **Response** | "`{priority, category, auto_reply, escalate, retrieved_faqs}`" |
| 8 | Rectangle (alert) | **Human Escalation Queue** | "Route to live agent (only when escalate = true)" |
| 9 | Cylinder/database | **Ticket Store** | "Persist ticket → `GET /tickets`" |

---

## 3. Arrows / Connectors

Label each arrow so the data flow is explicit:

1. **Customer Message → FastAPI Service** — label: `customer_message (JSON)`
2. **FastAPI → Claude Classifier** — label: `message text`
3. **Claude Classifier → FastAPI** (return) — label: `priority + category`
4. **FastAPI → RAG Retrieval** — label: `query = message`
5. **RAG Retrieval → FastAPI** (return) — label: `top-K FAQs + scores`
6. **FastAPI → Claude Reply Generator** — label: `message + FAQ context`
7. **Claude Reply Generator → FastAPI** (return) — label: `grounded reply`
8. **FastAPI → Priority == high? (diamond)** — label: `evaluate priority`
9. **Diamond → Human Escalation Queue** — label: **`YES (escalate = true)`**
10. **Diamond → Response** — label: **`NO (escalate = false)`**
11. **Human Escalation Queue → Response** — label: `also returned to client`
12. **FastAPI → Ticket Store** — label: `save ticket`
13. **Ticket Store → Response** (dashed) — label: `GET /tickets reads here`

> Tip: make the two Claude calls (nodes 3 and 5) point **out** to a separate
> external box labeled **"Anthropic Claude API (`claude-sonnet-4-20250514`)"**
> with bidirectional arrows. This visually shows both LLM calls hit the same
> external service.

---

## 4. Grouping / Containers

Wrap nodes 2–6, 9 inside one large container box labeled
**"FastAPI Backend (stateless, horizontally scalable)"**. Keep these *outside*
that container:

- **Customer Message** (node 1) — top-left, outside.
- **Anthropic Claude API** — right side, outside (shared by nodes 3 & 5).
- **Human Escalation Queue** (node 8) — bottom, outside.
- **Response** (node 7) — output, to the right of the container.

---

## 5. Suggested Colors (for a polished look)

| Element | Fill | Border |
|---|---|---|
| Start / End (Customer Message, Response) | Light green `#D5F5E3` | Green `#27AE60` |
| FastAPI Service & container | Light blue `#D6EAF8` | Blue `#2E86C1` |
| Claude LLM nodes (Classifier, Reply Gen) | Light purple `#E8DAEF` | Purple `#8E44AD` |
| External Claude API box | Lavender `#EBDEF0` | Purple `#8E44AD`, dashed |
| RAG Retrieval / Ticket Store (data) | Light orange `#FDEBD0` | Orange `#E67E22` |
| Decision diamond | Light yellow `#FCF3CF` | Amber `#F1C40F` |
| Human Escalation Queue | Light red `#FADBD8` | Red `#E74C3C` |

---

## 6. ASCII Reference (what the finished diagram conveys)

```
 ┌────────────────────┐
 │  Customer Message  │   (web · app · email)
 └─────────┬──────────┘
           │ customer_message (JSON)
           ▼
 ╔═══════════════════════════════════════════════════════════════╗
 ║                  FastAPI Backend (stateless)                    ║
 ║                                                                 ║
 ║   ┌──────────────────┐  message       ┌───────────────────┐    ║
 ║   │ Claude Classifier│ ─────────────► │                   │    ║
 ║   │ (forced tool call)│ ◄───────────── │  Anthropic Claude │    ║
 ║   └────────┬─────────┘ priority+cat    │  API              │    ║
 ║            ▼                            │ claude-sonnet-... │    ║
 ║   ┌──────────────────┐                 │                   │    ║
 ║   │  RAG Retrieval   │ TF-IDF+cosine   │                   │    ║
 ║   │ (in-memory FAQ)  │  top-K FAQs     │                   │    ║
 ║   └────────┬─────────┘                 │                   │    ║
 ║            ▼  message + FAQ context     │                   │    ║
 ║   ┌──────────────────┐ ─────────────► │                   │    ║
 ║   │ Claude Reply Gen │ ◄───────────── │                   │    ║
 ║   │  (grounded)      │  reply text     └───────────────────┘    ║
 ║   └────────┬─────────┘                                          ║
 ║            ▼                                                     ║
 ║      < priority == high? >                                       ║
 ║         │YES        │NO                                          ║
 ║         ▼           ▼                                            ║
 ║  ┌────────────┐  ┌──────────────┐    ┌──────────────────┐       ║
 ║  │ Escalation │  │   Response   │    │   Ticket Store   │       ║
 ║  │   Queue    │  │ (+ escalate) │◄───│  GET /tickets    │       ║
 ║  └────────────┘  └──────────────┘    └──────────────────┘       ║
 ╚═══════════════════════════════════════════════════════════════╝
```

---

## 7. One-line summary to caption the diagram

> "A customer message flows into a FastAPI service that calls Claude to classify
> priority and category, retrieves grounding FAQs via in-memory cosine
> similarity, asks Claude to draft a grounded reply, and returns a response —
> automatically flagging high-priority tickets for human escalation."
