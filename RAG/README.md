# GCC Job Market Intelligence System
### RAG-Powered Labor Market Analytics Chatbot

> Built at **HBKU (Hamad Bin Khalifa University)** · Data sources: **Bayt.com + LinkedIn** · QCRI Internship 2026

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![Qdrant](https://img.shields.io/badge/Vector_DB-Qdrant_Cloud-red)](https://qdrant.tech)
[![Fanar](https://img.shields.io/badge/LLM-Fanar%20%7C%20OpenAI-purple)](https://api.fanar.qa)
[![Next.js](https://img.shields.io/badge/Frontend-Next.js-black)](https://nextjs.org)

---

## What This System Does

A conversational AI assistant that answers natural language questions about the Gulf job market using **real data scraped from Bayt.com and LinkedIn**. It combines semantic search, SQL analytics, and large language models to give accurate, data-grounded answers — in both **English and Arabic**.

**Example questions it can answer:**
- *"What is the average salary for a Data Analyst in Qatar?"*
- *"Which sector is hiring the most in Saudi Arabia right now?"*
- *"I'm a fresh AI graduate — which companies should I apply to and what skills do I need?"*
- *"Compare Qatar vs UAE construction job market"*
- *"What are the top in-demand skills across the GCC?"*
- *"ما هي المهارات المطلوبة لوظائف البرمجة في الإمارات؟"* (Arabic supported)

---

## Dataset

### Bayt.com (English + Arabic)

| File | Country | Date | Postings |
|---|---|---|---|
| `bayt_jobs_Qatar_12_May_2026.xlsx` | Qatar | May 2026 | 2,376 |
| `bayt_jobs_Qatar_AR_12_May_2026.xlsx` | Qatar | May 2026 | 2,318 (Arabic portal) |
| `bayt_jobs_Saudi_Arabia_12_May_2026.xlsx` | Saudi Arabia | May 2026 | 8,236 |
| `bayt_jobs_Saudi_Arabia_AR_12_May_2026.xlsx` | Saudi Arabia | May 2026 | Arabic portal |
| `bayt_jobs_UAE_12_May_2026.xlsx` | UAE | May 2026 | 9,923 |
| `bayt_jobs_UAE_AR_12_May_2026.xlsx` | UAE | May 2026 | Arabic portal |

### LinkedIn (LLM-Enriched)

| File | Country | Date |
|---|---|---|
| `linkedin_Jobs_Qatar_7_June_2026_LLM_Enriched_22_Jun_2026.xlsx` | Qatar | Jun 2026 |
| `linkedin_jobs_Qatar_1_June_2026_LLM_Enriched_22_Jun_2026.xlsx` | Qatar | Jun 2026 |
| `linkedin_Jobs_Saudi_Arabia_7_June_2026_LLM_Enriched_22_Jun_2026.xlsx` | Saudi Arabia | Jun 2026 |
| `linkedin_jobs_Saudi_Arabia_1_June_2026_LLM_Enriched_22_Jun_2026.xlsx` | Saudi Arabia | Jun 2026 |
| `linkedin_Jobs_UAE_1_June_2026_LLM_Enriched_22_Jun_2026.xlsx` | UAE | Jun 2026 |
| `linkedin_jobs_UAE_7_June_2026_LLM_Enriched_22_Jun_2026.xlsx` | UAE | Jun 2026 |

**Total: ~30,795 job postings** across 3 GCC countries, 2 sources, 2 time periods. LinkedIn scrapes are automatically deduplicated by Job ID.

**Naming conventions (drop any new file — system picks it up automatically):**
```
bayt_jobs_{Country}_{DD}_{Mon}_{YYYY}.xlsx
bayt_jobs_{Country}_AR_{DD}_{Mon}_{YYYY}.xlsx     ← Arabic portal (optional, same jobs)
linkedin_jobs_{Country}_{DD}_{Mon}_{YYYY}_*.xlsx  ← LinkedIn (any suffix after date)
```

---

## Project Structure

```
GCC-Job-Market-RAG/
│
├── 📄 server.py               FastAPI backend — all /api/* endpoints
├── 📄 rag_engine.py           Core RAG pipeline (HyST-inspired, 3-layer retrieval)
├── 📄 data_loader.py          Data ingestion, normalisation, Bayt+LinkedIn parsing
├── 📄 vector_store.py         Qdrant Cloud wrapper (multilingual semantic indexing)
├── 📄 analytics.py            Pandas statistics engine (salary, skills, sectors)
├── 📄 sql_engine.py           Text-to-SQL layer (structured/counting queries)
├── 📄 config.py               Global settings, API keys, model routing
├── 📄 app.py                  Streamlit UI (legacy dashboard — still functional)
├── 📄 build_index.py          Offline index builder (run before deploying)
├── 📄 evaluate_mcq.py         MCQ benchmark runner (EN + AR accuracy evaluation)
├── 📄 summarize_results.py    Turns benchmark JSON → Excel + text scorecard
├── 📄 generate_benchmark.py   Generates open-ended QA benchmark from data
├── 📄 generate_mcq_from_source.py  Generates MCQ benchmark from raw job data
├── 📄 requirements.txt        Python dependencies
│
├── 📁 frontend/               Next.js web application (primary UI)
│   ├── app/                   Next.js App Router pages
│   ├── components/            React components (Chat, Dashboard, Sidebar)
│   └── lib/                   API client, types
│
├── 📁 data/                   Job posting Excel files
│   ├── bayt_jobs_*.xlsx       Bayt.com English postings
│   ├── bayt_jobs_*_AR_*.xlsx  Bayt.com Arabic portal (merged by Job_ID)
│   └── linkedin_jobs_*.xlsx   LinkedIn postings (LLM-enriched metadata)
│
├── 📁 chroma_db/
│   └── _manifest.json         Tracks which files are indexed (filename hash)
│
├── 📁 RAG_Benchmark/          MCQ evaluation benchmark (from mentor)
│   ├── RAG_Benchmark_Jobs_GCC.xlsx          ~4,000 open-ended QAs
│   ├── RAG_Benchmark_Jobs_GCC_MCQ.xlsx      Same questions in MCQ form
│   └── RAG_MCQ_Jobs_GCC_FromSource.xlsx     Factual MCQs from raw job data
│
├── mcq_results.json           Latest benchmark run (raw per-question results)
├── mcq_results.xlsx           Benchmark results — Summary + Per-Question sheets
├── mcq_summary.txt            Copy-paste scorecard
│
├── .gitattributes             Git LFS rules
├── .gitignore                 Excludes .env, __pycache__, venv, logs
└── .env                       Local API keys (never committed)
```

---

## System Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DATA PIPELINE (offline)                      │
│                                                                       │
│  Bayt EN/AR + LinkedIn → data_loader.py → Normalisation → Qdrant    │
│  (auto-detected by          (country,        (career, sector,        │
│   filename pattern)          month, source)   employment type)        │
└─────────────────────────────────────────────────────────────────────┘
                              ↓ (pre-built, instant load)
┌─────────────────────────────────────────────────────────────────────┐
│                       QUERY PIPELINE (real-time)                     │
│                                                                       │
│  User selects datasets in sidebar (Bayt/LinkedIn, country, period)   │
│       │                                                               │
│  User Question                                                        │
│       │                                                               │
│       ▼                                                               │
│  [1] Query Decomposer (Fanar internal)                               │
│       Extracts: country filter, job title, timeline, sector           │
│       Classifies: ANALYTICAL / SEMANTIC / HYBRID                     │
│       │                                                               │
│       ├──────────────────────┬────────────────────────────┐          │
│       ▼                      ▼                            ▼          │
│  [2] SQL Layer          [3] Pandas Layer          [4] Qdrant         │
│   (Fanar internal)       (analytics.py)       (multilingual semantic) │
│   Counts, rankings,      Skills, salary,      Top-K similar postings │
│   comparisons            experience stats     scoped to selection    │
│       │                      │                            │          │
│       └──────────────────────┴────────────────────────────┘          │
│                              ▼                                        │
│                    [5] Context Assembly                               │
│                    SQL stats + Pandas stats + Retrieved postings      │
│                              ▼                                        │
│                    [6] LLM Generation (Fanar-C-2-27B)                │
│                    System prompt + context + user question            │
│                              ▼                                        │
│                    Streaming answer → Next.js UI                      │
└─────────────────────────────────────────────────────────────────────┘
```

### The 3-Layer Retrieval (HyST-Inspired)

Inspired by the **HyST (2025)** paper on hybrid retrieval over semi-structured tabular data:

| Layer | Technology | Handles |
|---|---|---|
| **Layer 1 — SQL** | SQLite + Fanar | Counts, rankings, averages, trend comparisons |
| **Layer 2 — Pandas** | pandas + analytics.py | Skills frequency, salary parsing, experience distribution |
| **Layer 3 — Semantic** | Qdrant + multilingual-MiniLM | Job matching, descriptions, role-specific queries (EN + AR) |

All three layers are **scoped to the user's active dataset selection** — if you select only LinkedIn Qatar, the chatbot only retrieves from those postings.

---

## Key Features

### 📊 Dashboard
- **KPI Cards** — Total postings, countries, companies, avg salary
- **Dynamic Filters** — Country, Sector, Timeline (derived from actual data)
- **Dataset Selector** — Toggle Bayt / LinkedIn, any country, any period independently
- **9 Chart Sections** — Postings by Sector, Salary, Career Level, Employment Type, Skills, Experience, Language, Locations, Top Companies
- **Country Comparison** — Auto-shows when multiple countries selected

### 💬 Chat (RAG)
- **Natural language Q&A** in English and Arabic
- **Dataset-scoped answers** — chatbot respects the same sidebar selection as the dashboard
- **Streaming responses** — token-by-token output
- **Retrieval Transparency Panel** — shows query type, layers used, semantic scores
- **Chat History** — last 3 turns used as context for follow-ups

### 🗂️ Sidebar
- **Source grouping** — datasets grouped as 📌 Bayt and 💼 LinkedIn
- **Granular selection** — tick any combination of source/country/period
- **Model selector** — switch between Fanar and OpenAI models per session

---

## Multilingual Support (English + Arabic)

The system handles Arabic end-to-end:

| Component | Arabic support |
|---|---|
| **Embedding model** | `paraphrase-multilingual-MiniLM-L12-v2` — same 384-dim space for EN + AR |
| **Indexed documents** | Each posting includes its Arabic text (`Original_Page_Content`) from the AR portal file, merged by Job_ID |
| **Vector search** | Arabic queries retrieve the correct Arabic/bilingual postings |
| **LLM (Fanar)** | Fanar-C-2-27B is Gulf-region and Arabic-aware |
| **Benchmark** | 82% Arabic accuracy vs 83% English (see Evaluation section) |

---

## LLM Architecture

```
Internal tasks (structured output required):
  Query Decomposer    →  Fanar internal model  → JSON output
  SQL Generator       →  Fanar internal model  → SQL query output

User-facing answer:
  Final Generation    →  Fanar-C-2-27B (Fanar)  → Streaming answer
```

**Available models (user-selectable):**
| Model | Provider | Best for |
|---|---|---|
| Fanar-C-2-27B | Fanar (Qatar) | Default, Arabic-aware, Gulf context |
| Fanar-C-1-8.7B | Fanar (Qatar) | Balanced speed/quality |
| Fanar-S-1-7B | Fanar (Qatar) | Fast responses |
| GPT-4o | OpenAI | Highest quality, complex analysis |
| GPT-4o Mini | OpenAI | Fast fallback |

---

## Embeddings & Vector Search

**Model:** `paraphrase-multilingual-MiniLM-L12-v2`
- 384-dimensional dense vectors (same dimension as all-MiniLM-L6-v2)
- Supports 50+ languages including Arabic
- Runs locally — no API cost

**Document format** (what gets embedded per job posting):
```
Country: Qatar
Timeline: May 2026
Job Title: Senior Software Engineer
Company: Qatar Foundation
Sector: Technology
...
Skills: Python; Machine Learning; AWS
Description: We are looking for...
النص الأصلي: نبحث عن مهندس برمجيات...   ← Arabic text merged from AR portal
```

**Vector DB:** Qdrant Cloud (replaces ChromaDB). Payload indexes on `_country`, `_timeline`, `_dump_id`, `_source` allow filtered semantic search.

---

## Evaluation / Benchmark

The system was evaluated against a **multiple-choice benchmark** created from the same job data, covering both English and Arabic questions.

### Results (200-question sample, May Bayt data)

```
Overall accuracy:  165/200 = 82.5%

By language:
  English   83/100 = 83.0%
  Arabic    82/100 = 82.0%   ← near-identical, multilingual index works

By country:
  Saudi Arabia   86.1%
  UAE            84.1%
  Qatar          76.3%
```

### Benchmark Files

| File | Description | Questions |
|---|---|---|
| `RAG_Benchmark_Jobs_GCC.xlsx` | Open-ended QA (question + paragraph answer) | ~4,000 |
| `RAG_Benchmark_Jobs_GCC_MCQ.xlsx` | Same questions as multiple choice (A/B/C/D) | ~4,000 |
| `RAG_MCQ_Jobs_GCC_FromSource.xlsx` | Factual MCQs generated from raw job data | ~2,700 |

### Running the Benchmark

```bash
# Quick sample (200 questions, ~30 min)
python evaluate_mcq.py --sample 50 --out mcq_results.json

# Full run (all usable questions, few hours)
python evaluate_mcq.py --full --out mcq_results.json

# Generate shareable Excel + text scorecard
python summarize_results.py
```

---

## Data Normalisation

Raw Bayt.com data has inconsistent field values. The system normalises using **substring matching**:

**Employment Type:**
```
"Full-Time" / "full time" / "FULL-TIME"  →  "Full-Time"
"Contract" / "contract-based"            →  "Contract"
```

**Career Level:**
```
"Mid-Level" / "متوسط الخبرة" / "Consultant"  →  "Mid-Level"
"Management" / "Manager" / "إدارة"           →  "Manager"
```

---

## Deployment

### Local Development

```bash
# 1. Clone
git clone https://github.com/mhdfaizjabir/jobmarket_bot.git
cd jobmarket_bot

# 2. Install Python dependencies
pip install -r RAG/requirements.txt

# 3. Create RAG/.env
OPENAI_API_KEY=sk-...
FANAR_API_KEY=...
QDRANT_URL=https://your-cluster.qdrant.io
QDRANT_API_KEY=...

# 4. Build vector index (one-time, ~30 min for all data)
cd RAG
python build_index.py

# 5a. Run backend
uvicorn server:app --port 8000 --reload

# 5b. Run frontend (separate terminal)
cd ../frontend
npm install
npm run dev
# Open http://localhost:3000
```

### Adding New Data

```bash
# Drop new file in RAG/data/ following naming convention
# Incremental index — only embeds new/changed files
cd RAG
python build_index.py

git add data/ chroma_db/_manifest.json
git commit -m "Add new data scrape"
git push
```

---

## File Modules — Detailed

### `config.py`
- `CHAT_MODEL` / `INTERNAL_MODEL` — LLM routing
- `EMBEDDING_MODEL` — `paraphrase-multilingual-MiniLM-L12-v2`
- `COLUMN_ALIASES` — maps all raw column name variants to canonical names
- `make_client(model)` — routes to Fanar or OpenAI

### `data_loader.py`
- `load_all(data_dir)` — scans folder, loads Bayt EN + LinkedIn files; merges Bayt AR by Job_ID
- `parse_file_info(path)` — extracts country, timeline, source (Bayt/LinkedIn), is_ar from filename
- Deduplicates overlapping LinkedIn scrapes by (dump_id, job_id)
- Tags each row with `_source` ("Bayt" or "LinkedIn")

### `vector_store.py`
- `VectorStore()` — wraps Qdrant Cloud REST client
- `build_index(df, files)` — full rebuild (deletes collection, re-embeds everything)
- `build_index_incremental(df, files)` — only embeds new/changed files
- `search(query, n, where)` — multilingual semantic search with metadata filter
- Supports `$eq` and `$in` filter operators

### `rag_engine.py`
HyST-inspired pipeline:
1. `_prepare(question, dump_ids)` — decompose + SQL, run once, carry `dump_ids` through
2. `_build_full_context()` — runs all 3 layers, scoped to selected datasets
3. `answer(question, dump_ids)` — streams final LLM response
4. `get_retrieval_info()` — returns transparency data (layers used, scores)

### `server.py`
FastAPI backend:
- `GET /api/datasets` — all dataset dumps with counts, timelines, sources
- `GET /api/dashboard` — all chart data for selected dump_ids
- `POST /api/chat` — streaming SSE chat with dataset scoping
- `POST /api/session` — session management

### `evaluate_mcq.py`
- Loads benchmark xlsx, filters to rows whose source files are present in `data/`
- Sends each MCQ to the RAG, parses letter answer (A/B/C/D), checks against correct answer
- Reports accuracy by language, benchmark file, country
- `--sample N` for quick runs, `--full` for complete evaluation

---

🔗 **GitHub:** [github.com/mhdfaizjabir/jobmarket_bot](https://github.com/mhdfaizjabir/jobmarket_bot)

> For project overview, team, research foundation and known limitations see the [root README](../README.md).
