<div align="center">

# 💰 Finance Overdue Agent

### Enterprise-Grade AI Agent for Automated Invoice Follow-Ups

Built with **LangGraph** · **Mistral AI** · **SQLite** · **APScheduler** · **LangSmith** · **Streamlit**

[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)]()
[![LangGraph](https://img.shields.io/badge/LangGraph-Agent%20Workflow-8A2BE2)]()
[![Mistral AI](https://img.shields.io/badge/Mistral-AI-orange)]()
[![Streamlit](https://img.shields.io/badge/Streamlit-Dashboard-red?logo=streamlit)]()
[![SQLite](https://img.shields.io/badge/SQLite-Audit%20Store-003B57?logo=sqlite)]()
[![LangSmith](https://img.shields.io/badge/LangSmith-Observability-1F8EFA)]()
[![License](https://img.shields.io/badge/License-MIT-green)]()

**Developed by [Ranbir Singh](https://github.com/ranveer193)**

---

### 🌐 [Live Demo](https://finance-overdue-agent.streamlit.app/) &nbsp;|&nbsp; 🔍 [Public LangSmith Trace](https://smith.langchain.com/public/a1a5ee0f-da41-48a1-a47e-c4cb4f8ed7f8/r) &nbsp;|&nbsp; ⭐ [GitHub](https://github.com/ranveer193/finance-overdue-agent)

</div>

---

## 🚀 Deployment Status

This project is currently deployed and running on Streamlit at the live demo URL above.
The app includes invoice upload workflows, AI-generated follow-ups, audit trails, retry handling, and dashboard monitoring for finance teams.

---

## 🎥 Project Demo Video

Watch the complete end-to-end demonstration of the Finance Overdue Agent, including:

- CSV invoice upload
- Automated stage classification
- AI-generated follow-up emails
- Human-in-the-loop approval workflow
- SQLite audit logs
- APScheduler retry handling
- LangSmith trace visualization
- Streamlit dashboard walkthrough

<div align="center">

[![Finance Overdue Agent Demo](https://img.youtube.com/vi/KHJBUM_inG8/maxresdefault.jpg)](https://www.youtube.com/watch?v=KHJBUM_inG8)

**▶️ Click the thumbnail above to watch the full demo on YouTube**

</div>

## 📌 Problem Statement

Finance teams spend significant time manually tracking overdue invoices, drafting reminder emails, escalating risky accounts, and maintaining audit trails. Errors, missed follow-ups, and inconsistent tone cost real money.

This project fully automates the accounts receivable follow-up lifecycle:

- Upload a CSV of invoice records
- Classify invoices by overdue stage automatically
- Generate professional, tone-adaptive follow-up emails via LLM
- Validate all generated outputs against deterministic business rules
- Support **human-in-the-loop** approval before sending which is currently paused in production
- Retry rejected drafts with reviewer feedback
- Escalate high-risk accounts to finance/legal review
- Persist every action to SQLite with full audit trails
- Retry transient failures automatically via APScheduler
- Observe every execution end-to-end with LangSmith
- Monitor the entire pipeline through a production-grade Streamlit dashboard

---

## ✨ Key Features

### 🤖 AI-Powered Email Generation
- Stage-specific tone adaptation (5 tones across 5 escalation levels)
- Structured output enforcement with Pydantic
- Deterministic subject line validation
- Automatic payment link insertion

### 🧠 Agentic Workflow with LangGraph
- Master orchestration graph with a dedicated worker subgraph
- Conditional routing based on overdue stage and validation outcome
- Retry and validation loops
- LangGraph checkpoint-based state recovery

### 👨‍💼 Human-in-the-Loop Approval
- Finance teams review and approve every draft before it is sent
- Rejected emails enter a structured retry loop with reviewer feedback
- Manual escalation path for accounts requiring legal review

### 📊 Dashboard & Monitoring
- **Upload** — CSV ingestion with SHA-256 deduplication
- **Jobs Dashboard** — real-time metrics, job statuses, success rates
- **Audit Logs** — per-invoice history, validation status, retry counts
- **Email Logs** — dry-run previews in terminal-style view
- **Failed Invoice Queue** — retry queue with error inspection

### 🛡️ Enterprise Controls
- SQLite audit storage with atomic transactions
- PII masking in all log outputs
- File hashing and deduplication (SHA-256)
- APScheduler for scheduled retries with exponential backoff
- LangSmith end-to-end tracing and token usage monitoring
- Parameterized SQL queries (no raw string interpolation)

### ⚡ Performance Optimizations
- Batch processing across invoice groups
- Background job execution (non-blocking UI)
- File-level caching to prevent duplicate processing
- Configurable delay and backoff parameters

---

## 🏗️ Architecture Overview

### End-to-End Workflow

```text
Invoice CSV Upload
        │
        ▼
SHA-256 File Hash → Duplicate Check
        │
        ▼
Job Record Created in SQLite
        │
        ▼
Background Worker Starts
        │
        ▼
CSV Loaded & Normalized
        │
        ▼
Invoices Grouped by Follow-Up Stage
        │
        ▼
Batches Created
        │
        ▼
Worker Subgraph (per invoice)
        │
        ├─► Overdue Calculation
        │
        ├─► Stage Selection
        │
        ├─► Email Generation (LLM — Mistral AI)
        │
        ├─► Deterministic Validation
        │
        ├─► Human Approval
        │         ├─ Approve ──► Send Email
        │         └─ Reject  ──► Retry with Feedback
        │
        ├─► Audit Log Persisted to SQLite
        │
        ├─► Failures Stored for APScheduler Retry
        │
        └─► If 30+ Days → Manager Escalation
                │
                ▼
        Metrics Updated → Dashboard Refreshed → LangSmith Trace Complete
```

### Master Workflow Diagram
![Upload](https://raw.githubusercontent.com/ranveer193/finance-overdue-agent/main/assets/master_flow.png)

### Worker Workflow Diagram
![Upload](https://raw.githubusercontent.com/ranveer193/finance-overdue-agent/main/assets/worker_flow.png)

---

## 📬 Follow-Up Stages

| Days Overdue | Stage | Tone | Action |
|---:|---|---|---|
| 0 or future | No Overdue | No Action Required | Skip — no email sent |
| 1–7 | 1st Follow-Up | Warm & Friendly | Gentle reminder |
| 8–14 | 2nd Follow-Up | Polite but Firm | Request payment confirmation date |
| 15–21 | 3rd Follow-Up | Formal & Serious | Response required within 48 hours |
| 22–30 | 4th Follow-Up | Stern & Urgent | Final notice before collections |
| 31+ | Escalation Flag | Legal Review Required | Manual finance/legal escalation |

---

## 📷 Sample Email Outputs

### 🟢 Stage 1 — Friendly Reminder (2 Days Overdue)

```
Subject : Quick Reminder – Invoice #INV-2026-101 | ₹45,251 Due
Tone    : Warm & Friendly

Hi ABC Technologies Pvt Ltd Team,

Hope all is well! We wanted to reach out regarding Invoice #INV-2026-101,
which appears to have been overlooked.

Amount Due : ₹45,250.75
Due Date   : 8 May 2026

Pay here: https://pay.company.com/INV-2026-101
```

---

### 🟡 Stage 2 — Polite Follow-Up (10 Days Overdue)

```
Subject : Payment Follow-Up – Invoice #INV-2026-101 (10 Days Overdue)
Tone    : Polite but Firm

Dear ABC Technologies Pvt Ltd Team,

Invoice #INV-2026-101 for ₹45,250.75 was due on 30 April 2026.
This invoice is currently 10 days overdue.

Could you please confirm the expected payment date?

Pay here: https://pay.company.com/INV-2026-101
```

---

### 🟠 Stage 3 — Formal Reminder (18 Days Overdue)

```
Subject : IMPORTANT: Outstanding Payment – Invoice #INV-2026-101 (18 Days Overdue)
Tone    : Formal & Serious

Dear ABC Technologies Pvt Ltd Team,

Invoice #INV-2026-101 remains unpaid and is now 18 days overdue.
Despite previous reminders, no payment or confirmation has been received.

Please respond within 48 hours.

Pay here: https://pay.company.com/INV-2026-101
```

---

### 🔴 Stage 4 — Final Notice (23 Days Overdue)

```
Subject : FINAL NOTICE – Invoice #INV-2026-101 – Immediate Action Required
Tone    : Stern & Urgent

Dear ABC Technologies Pvt Ltd Team,

This is the final notice regarding Invoice #INV-2026-101.
The payment is now 23 days overdue.

This is your last opportunity to settle before escalation to our collections partner.

Pay here: https://pay.company.com/INV-2026-101
```

---

### 🚨 Stage 5 — Manager Escalation (38 Days Overdue)

```
To      : finance.manager@company.com
Subject : Escalation Required — Invoice INV-2026-101

Invoice INV-2026-101 for client ABC Technologies Pvt Ltd
is 38 days overdue and requires immediate manual review.
```

---

## 👨‍💼 Human-in-the-Loop Approval Flow

```text
Generated Email Draft
        │
        ▼
Finance Team Review
        │
        ├─ approve ──► Email Sent + Audit Log Written
        │
        └─ reject  ──► Reviewer Feedback Collected
                               │
                               ▼
                        Retry with Feedback (up to max_retries)
                               │
                               ▼
                        Re-validation → Re-approval
```

Every email can be reviewed, rejected with explicit feedback, and regenerated before it leaves the system.

---

## 📝 Audit Log Structure

```text
invoice_no        : INV-2026-101
client            : ABC Technologies Pvt Ltd
amount            : 45250.75
days_overdue      : 23
stage_key         : 4th Follow-Up
tone_used         : Stern & Urgent
validation_status : approved
send_status       : sent
retry_count       : 0
max_retries       : 3
```

---

## 🧩 Technology Stack

| Layer | Technology |
|---|---|
| LLM | Mistral AI |
| Agent Framework | LangGraph |
| LLM Orchestration | LangChain |
| Output Validation | Pydantic |
| UI / Dashboard | Streamlit |
| Database | SQLite |
| Job Scheduler | APScheduler |
| Observability | LangSmith |
| Configuration | python-dotenv |

---

## 💾 SQLite Data Model

| Table | Purpose |
|---|---|
| `jobs` | Uploaded job metadata and aggregated metrics |
| `audit_logs` | One record per invoice processed |
| `failed_invoices` | Recoverable failures for scheduled retries |

---

## 🔐 Security Design

| Risk | Mitigation |
|---|---|
| API key exposure | Secrets stored in `.env`, never committed |
| Duplicate submissions | SHA-256 file hashing |
| PII leakage | Email masking in all log outputs |
| Invalid AI outputs | Deterministic validation rules |
| Prompt injection | Strict prompt schemas and Pydantic enforcement |
| Lost failures | Persistent retry queue in SQLite |
| Silent failures | LangSmith tracing + audit logs |
| Rate limit errors | Exponential backoff with configurable ceiling |
| Unsafe SQL | Parameterized queries only |
| Corrupt state | Atomic SQLite transactions |

---

## ⚡ Retry Strategy

**Immediate Retries** (during processing)
- HTTP 429 rate limit errors
- Temporary provider outages
- Capacity errors

**Scheduled Retries** (APScheduler)
- Runs every `FAILED_INVOICE_SCHEDULER_INTERVAL_MINUTES` minutes
- Processes up to `FAILED_INVOICE_BATCH_SIZE` records per run
- Backoff capped at `FAILED_INVOICE_MAX_BACKOFF_MINUTES`

---

## 📊 Sample Run Metrics

From a representative run of 15 invoices:

| Metric | Value |
|---|---|
| Total Invoices | 15 |
| Emails Sent | 6 |
| Escalated | 4 |
| Not Overdue | 5 |
| Failed | 0 |
| Success Rate | 100% |

---

## 📁 Project Structure

```text
finance-overdues-agent/
├── app.py                    # Streamlit dashboard entry point
├── run_cli.py                # CLI runner
├── workflow.py               # Master LangGraph orchestration graph
├── invoice_workflow.py       # Worker subgraph
├── graph.py                  # Graph definitions
├── prompts.py                # LLM prompt templates
├── models.py                 # Pydantic models
├── utils.py                  # Shared utilities
├── config.py                 # Environment configuration
│
├── nodes/                    # LangGraph node implementations
│
├── background/
│   ├── executor.py           # Background job runner
│   └── run_job.py            # Job execution logic
│
├── database/
│   ├── db.py                 # Database connection
│   ├── schema.py             # Table definitions
│   ├── jobs_repository.py
│   ├── audit_repository.py
│   └── failed_repository.py
│
├── data/
│   ├── uploads/              # Uploaded CSV files
│   └── finance_agent.db      # SQLite database
│
├── logs/
│   └── email_dry_run.jsonl   # Dry-run email log
│
├── requirements.txt
├── .env.example
└── README.md
```

---

## 📄 Sample CSV Input Format

```csv
invoice_number,client_name,amount,due_date,recipient_email
INV-2026-001,Acme Corp,45000,2026-04-15,accounts@acme.com
INV-2026-002,Orbit Logistics,125000,2026-04-20,payments@orbit.com
```

---

## ⚙️ Environment Variables

```env
# LLM
MISTRAL_API_KEY="your_api_key_here"

# LangSmith Observability
LANGCHAIN_TRACING_V2="true"
LANGCHAIN_ENDPOINT="https://api.smith.langchain.com"
LANGCHAIN_API_KEY="your_api_key_here"
LANGCHAIN_PROJECT="Finance Overdue Agent"

# Email
EMAIL_PROVIDER="dry_run"           # dry_run | sendgrid | mailgun
DRY_RUN_LOG_PATH="logs/email_dry_run.jsonl"

# Retry Configuration
WORKER_MAX_RETRY_ATTEMPTS=5
WORKER_INITIAL_BACKOFF_SECONDS=2
WORKER_DELAY_BETWEEN_INVOICES=1

# APScheduler
FAILED_INVOICE_SCHEDULER_INTERVAL_MINUTES=5
FAILED_INVOICE_BATCH_SIZE=100
FAILED_INVOICE_MAX_BACKOFF_MINUTES=60
FAILED_INVOICE_SCHEDULER_TIMEZONE=UTC
FAILED_INVOICE_SCHEDULER_MISFIRE_GRACE_SECONDS=60
```

---

## 🚀 Installation

### 1. Clone the Repository

```bash
git clone https://github.com/ranveer193/finance-overdue-agent.git
cd finance-overdue-agent
```

### 2. Create and Activate Virtual Environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment

```bash
cp .env.example .env
# Edit .env and add your API keys
```

### 5. Get a Free Mistral API Key

1. Sign up at [console.mistral.ai](https://console.mistral.ai/)
2. Navigate to [admin.mistral.ai/organization/api-keys](https://admin.mistral.ai/organization/api-keys)
3. Create a new key and paste it into `.env`

---

## ▶️ Running the Application

### Streamlit Dashboard

```bash
streamlit run app.py
```

---

## ☁️ Deployment

**Live deployment:** [finnace-overdues-agent-12.streamlit.app](https://finnace-overdues-agent-12.streamlit.app/)

Recommended hosting platforms:

- Streamlit Community Cloud
- Render
- Railway
- Azure App Service
- AWS ECS

---

## 📸 Application Screenshots

| View | Preview |
|---|---|
| 📤 Upload Dashboard | ![Upload](https://raw.githubusercontent.com/ranveer193/finance-overdue-agent/main/assets/upload_dashboard.png) |
| 📋 Jobs Dashboard | ![Jobs](https://raw.githubusercontent.com/ranveer193/finance-overdue-agent/main/assets/jobs_dashboard.png) |
| 🔎 Audit Logs | ![Audit](https://raw.githubusercontent.com/ranveer193/finance-overdue-agent/main/assets/audit_logs.png) |
| 📧 Email Logs | ![Email](https://raw.githubusercontent.com/ranveer193/finance-overdue-agent/main/assets/email_logs.png) |
| ⚠️ Failed Invoices | ![Failed](https://raw.githubusercontent.com/ranveer193/finance-overdue-agent/main/assets/failed_invoices.png) |
| 🔍 LangSmith Trace | ![LangSmith](https://raw.githubusercontent.com/ranveer193/finance-overdue-agent/main/assets/langsmith_trace.png) |

---

## 📚 Engineering Highlights

This project demonstrates production-grade AI engineering practices evaluated in senior roles:

- Multi-step **LangGraph** agentic workflow design
- Structured LLM outputs with **Pydantic** schema enforcement
- **Human-in-the-loop** approval with feedback-driven retry
- LangGraph **checkpoint-based** state recovery
- Background processing with non-blocking UI
- Persistent retry systems with exponential backoff
- End-to-end **LangSmith** observability (tokens, latency, errors)
- Security-aware design (PII masking, SQL injection prevention, deduplication)

---

## 🎯 Business Impact

- Eliminates manual follow-up effort for finance teams
- Standardizes communication tone across all escalation stages
- Improves collection efficiency through consistent, timely outreach
- Provides complete, tamper-evident auditability per invoice
- Prevents missed escalations on high-risk accounts
- Enables fully unattended batch processing overnight

---

## 🛣️ Future Roadmap

- [ ] Real SMTP delivery (SendGrid / Mailgun integration)
- [ ] ERP integrations (SAP, Oracle, NetSuite, Zoho Books)
- [ ] Role-based access control (RBAC)
- [ ] Multi-language email generation
- [ ] PDF invoice attachment support
- [ ] Webhook integrations for real-time triggers
- [ ] Approval workflow UI (in-dashboard approve/reject)
- [ ] Analytics dashboard with collection trend charts
- [ ] Scheduled follow-ups (calendar-based automation)

---

## 📦 Deliverables

- ✅ Complete source code
- ✅ `.env.example` configuration template
- ✅ `requirements.txt`
- ✅ Production-ready Streamlit dashboard
- ✅ LangSmith observability integration
- ✅ SQLite persistence with audit trail
- ✅ APScheduler retry system
- ✅ Human-in-the-loop approval flow
- ✅ Public live deployment
- ✅ Public LangSmith trace

---

## 📜 License

This project is licensed under the **MIT License**.

---

<div align="center">

Developed with precision by **Ranbir Singh**

⭐ If this project was useful to you, consider [starring the repository](https://github.com/ranveer193/finance-overdue-agent)

</div>
