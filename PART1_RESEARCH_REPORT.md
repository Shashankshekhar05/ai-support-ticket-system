# Part 1 — Research & Evaluation Report

**AI Tooling for Customer Support Automation**
*Prepared by: Shashank Shekhar — AI Engineer 

---

## 1. Scope

This report evaluates two categories of tooling for building an AI-powered
customer support automation system:

1. **Foundation LLMs** — OpenAI GPT-4o, Anthropic Claude (Sonnet family),
   Google Gemini 1.5 Pro.
2. **Orchestration / automation frameworks** — LangChain, n8n, CrewAI.

Each is compared on **Capabilities, Pricing, Scalability, Ease of Integration,
Limitations, and Best Use Cases**.

> Pricing figures are list prices at the time of writing and are rounded for
> comparison. Always confirm against each vendor's current pricing page before
> committing to a budget — model prices change frequently.

---

## 2. Foundation LLM Comparison

### 2.1 Capabilities

| Capability | OpenAI GPT-4o | Anthropic Claude (Sonnet) | Google Gemini 1.5 Pro |
|---|---|---|---|
| Context window | ~128K tokens | 200K (legacy) → up to **1M** on newer Sonnet | **1M–2M** tokens |
| Multimodal | Text, image, audio, real-time voice | Text, image (vision), PDF/doc native | Text, image, audio, video |
| Structured output | JSON mode, function/tool calling, strict schemas | Tool use, structured outputs, forced tool calls | Function calling, JSON schema |
| Reasoning quality | Excellent, fast | Excellent — strong at instruction-following & long-doc grounding | Very good; strongest on very long inputs |
| Long-document RAG | Good | **Very strong** (built for long-context grounding) | **Very strong** (huge context) |
| Tone / safety control | Good | **Best-in-class** steerability & refusal calibration | Good |

**Takeaway:** For a *support* assistant — where faithfully grounding replies in
retrieved policy text and following tone rules matter most — Claude's
instruction-following and long-context grounding are a strong fit. GPT-4o leads
on real-time voice; Gemini leads on raw context length and video.

### 2.2 Pricing (per 1M tokens, approximate list)

| Model | Input | Output | Notes |
|---|---|---|---|
| GPT-4o | ~$2.50 | ~$10.00 | Cheaper "mini" tier (~$0.15/$0.60) for high volume |
| Claude Sonnet | ~$3.00 | ~$15.00 | Prompt caching cuts repeat-context cost up to ~90% |
| Gemini 1.5 Pro | ~$1.25–$2.50 | ~$5.00–$10.00 | Tiered by prompt size; cheaper "Flash" tier available |

All three offer **prompt caching** and **batch** discounts that materially lower
real-world cost for support workloads with stable system prompts and FAQ
context (exactly our use case).

### 2.3 Scalability

| | GPT-4o | Claude Sonnet | Gemini 1.5 Pro |
|---|---|---|---|
| Rate limits | High, tier-based | High, tier-based | High, tied to GCP quotas |
| Batch API | Yes (50% off) | Yes (50% off) | Yes |
| Multi-cloud | Azure OpenAI | AWS Bedrock, GCP Vertex, Azure Foundry | GCP Vertex AI native |
| Latency | Very low | Low | Low–moderate |

All three scale to production support volumes. Claude's availability across AWS
Bedrock / Vertex / Azure gives the most deployment flexibility; Gemini is
tightest-integrated with GCP.

### 2.4 Ease of Integration

- **GPT-4o** — Largest ecosystem, most tutorials, mature Python/JS SDKs.
- **Claude** — Clean official SDKs (Python, TS, Go, Java, etc.), excellent
  tool-use ergonomics, first-class prompt caching. Very low friction.
- **Gemini** — Best when you already live in GCP/Vertex; SDK is solid but the
  surrounding ecosystem is smaller than OpenAI's.

### 2.5 Limitations

| Model | Key limitations for support automation |
|---|---|
| GPT-4o | Output price on the higher side; occasional verbosity; voice features are overkill for text tickets. |
| Claude Sonnet | No first-party embeddings API (use a separate embeddings provider or local vectors); premium output pricing. |
| Gemini 1.5 Pro | Strongest value is inside GCP; ecosystem/tooling less mature; behavior can vary more across regions. |

### 2.6 Best Use Cases

- **GPT-4o** — Real-time **voice** support bots, broad general-purpose agents,
  teams already on Azure/OpenAI.
- **Claude Sonnet** — **Policy-grounded text support**, RAG over long
  knowledge bases, strict-tone brand replies, classification/triage. *(Chosen
  for this project — see Part 3.)*
- **Gemini 1.5 Pro** — Massive-context ingestion (entire manuals, transcripts,
  video), GCP-native stacks.

---

## 3. Orchestration / Automation Framework Comparison

### 3.1 Capabilities

| | LangChain | n8n | CrewAI |
|---|---|---|---|
| Paradigm | Code-first LLM app framework | Visual workflow / automation (low-code) | Multi-agent orchestration framework |
| Primary user | Python/JS developers | Ops, integrators, semi-technical | Python developers building agent teams |
| RAG support | Rich (loaders, splitters, vector stores, retrievers) | Via nodes / external services | Via tools you wire in |
| Tool/agent support | Agents, tools, memory, LCEL chains | 400+ prebuilt integration nodes | Role-based agents, tasks, crews |
| State / memory | Built-in memory abstractions | Workflow state, queue mode | Shared crew context |

### 3.2 Pricing

| | LangChain | n8n | CrewAI |
|---|---|---|---|
| Core library | **Free / open source** | **Open source** (fair-code license) | **Free / open source** |
| Paid tier | LangSmith (observability) usage-based | n8n Cloud (hosted) subscription | CrewAI enterprise/cloud tiers |
| Self-host | Yes | Yes (Docker) | Yes |

You pay primarily for the underlying **LLM tokens** plus optional hosted/observability tiers.

### 3.3 Scalability

| | LangChain | n8n | CrewAI |
|---|---|---|---|
| Scaling model | As scalable as the app you build around it | Horizontal via queue mode + workers | Scales with your Python service |
| Throughput | High (you control it) | High for event/automation workloads | Moderate; agent loops add overhead |
| Statefulness | App-defined | Durable workflow execution | In-process crew runs |

### 3.4 Ease of Integration

- **LangChain** — Steep-ish learning curve, but maximum control; huge connector
  library. Best for embedding LLM logic *inside* a custom backend (like our FastAPI app).
- **n8n** — Easiest to start with (drag-and-drop), great for connecting Claude
  to Slack/Zendesk/email/CRM without much code.
- **CrewAI** — Easy if your problem genuinely decomposes into collaborating
  agents; otherwise it adds conceptual overhead.

### 3.5 Limitations

| | Limitations |
|---|---|
| LangChain | Abstractions churn between versions; can feel heavy for simple pipelines. |
| n8n | Visual flows get unwieldy for complex branching logic; less "code-native". |
| CrewAI | Multi-agent loops increase latency, token cost, and unpredictability; overkill for single-step triage. |

### 3.6 Best Use Cases

- **LangChain** — Custom RAG backends, retrieval pipelines, when you want
  code-level control (e.g. integrate into an existing service).
- **n8n** — Glue/automation: route Claude's output to Zendesk, Slack, email,
  databases, CRMs — minimal code.
- **CrewAI** — Genuinely multi-agent workflows (e.g. a triage agent + a research
  agent + a drafting agent collaborating).

---

## 4. Summary Recommendation

For an **AI customer support ticket system** that classifies, retrieves policy
context, and drafts grounded replies:

- **Model:** **Anthropic Claude (Sonnet)** — best balance of grounding fidelity,
  tone control, structured tool use, and multi-cloud availability.
- **Orchestration:** For this prototype, **no heavy framework is required** — a
  thin FastAPI service with a lightweight in-process RAG retriever is simpler,
  faster, and easier to reason about than LangChain/CrewAI. As the system grows,
  **n8n** is the natural choice for wiring Claude into downstream tools
  (Zendesk, Slack, email), and **LangChain** if/when retrieval grows complex
  enough to warrant its abstractions.

See **Part 3 — Recommendation Report** for the full architecture and the
detailed rationale for choosing Claude over GPT-4o and Gemini.
