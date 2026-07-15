# GCC Job Market Intelligence System
### RAG-Powered Labor Market Analytics Chatbot

> Built at **HBKU (Hamad Bin Khalifa University)** · Data sources: **Bayt.com + LinkedIn** · QCRI Internship 2026

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![Qdrant](https://img.shields.io/badge/Vector_DB-Qdrant_Cloud-red)](https://qdrant.tech)
[![Fanar](https://img.shields.io/badge/LLM-Fanar%20%7C%20OpenAI-purple)](https://api.fanar.qa)
[![Next.js](https://img.shields.io/badge/Frontend-Next.js-black)](https://nextjs.org)

A conversational AI assistant that answers natural language questions about the Gulf job market using **~30,000 real job postings from Bayt.com and LinkedIn** across Qatar, Saudi Arabia, and UAE — in both **English and Arabic**.

---

## Quick Start

```bash
# Backend (RAG API)
cd RAG
uvicorn server:app --port 8000 --reload

# Frontend (separate terminal)
cd frontend
npm install && npm run dev
```

Open **http://localhost:3000**

See [RAG/README.md](RAG/README.md) for full backend setup.

---

## Documentation

| Document | Covers |
|---|---|
| [PROJECT_SPEC.md](PROJECT_SPEC.md) | Living spec + full sprint history (what shipped, when, why) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the system fits together — request/RAG/filter/SQL/Qdrant flows |
| [API.md](API.md) | Every HTTP endpoint, request/response shapes, validation rules |
| [SECURITY.md](SECURITY.md) | Threat model, implemented controls, pre-deploy checklist |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Local / Docker / production (nginx) deployment |
| [OBSERVABILITY.md](OBSERVABILITY.md) | Prometheus metrics, Sentry/Langfuse activation |
| [RUNBOOK.md](RUNBOOK.md) | Operational procedures (restart, reindex, incident response) |

---

## Known Limitations

1. **Salary data is sparse** — only ~7% of postings disclose salary. All salary stats are based on this subset.
2. **Data is a snapshot** — postings scraped at specific dates. Job market changes daily.
3. **Source coverage** — covers Bayt.com and LinkedIn only, not the full GCC market.
4. **Arabic bilingual enrichment** — requires the corresponding `_AR_` file to be present for each Bayt EN file. LinkedIn has no Arabic portal equivalent.

---

## Research Foundation

| Paper | Contribution |
|---|---|
| **HyST (2025)** — Hybrid Retrieval over Semi-Structured Tabular Data | Query decomposition into SQL + semantic layers |
| **NLP-based Job Market Analysis** | Skill extraction, sector classification |
| **LLM Skill Extraction** | Structured extraction from unstructured job descriptions |

---

## Team

| Role | Contributor |
|---|---|
| RAG System, Pipeline, UI, Evaluation | Mohammad Faiz Jabir |
| Data Collection & Preprocessing | Albaraa |
| Benchmark Design & Validation | Mentor / Supervisor |
| Supervision | Dr. Hamdy |

**Institution:** Hamad Bin Khalifa University (HBKU) — QCRI Internship 2026
