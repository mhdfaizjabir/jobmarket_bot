# GCC Job Market Intelligence System
### RAG-Powered Labor Market Analytics Chatbot

> Built at **HBKU (Hamad Bin Khalifa University)** · Data source: **Bayt.com** · Internship Project 2026

[![Streamlit](https://img.shields.io/badge/Streamlit-1.57-red)](https://streamlit.io)
[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-1.5.5-green)](https://www.trychroma.com)
[![Fanar](https://img.shields.io/badge/LLM-Fanar%20%7C%20OpenAI-purple)](https://api.fanar.qa)

---

## What This System Does

A conversational AI assistant that answers natural language questions about the Gulf job market using **real data scraped from Bayt.com**. It combines semantic search, SQL analytics, and large language models to give accurate, data-grounded answers.

**Example questions it can answer:**
- *"What is the average salary for a Data Analyst in Qatar?"*
- *"Which sector is hiring the most in Saudi Arabia right now?"*
- *"I'm a fresh AI graduate — which companies should I apply to and what skills do I need?"*
- *"Compare Qatar vs UAE construction job market"*
- *"What are the top in-demand skills across the GCC?"*

---

## Live Demo

🔗 **[jobmarketbot.streamlit.app](https://jobmarketbot.streamlit.app)**

---

## Dataset

| File | Country | Date | Postings |
|---|---|---|---|
| `bayt_jobs_Qatar_22_Nov_2025.xlsx` | Qatar | Nov 2025 | 1,880 |
| `bayt_jobs_Qatar_22_Feb_2026.xlsx` | Qatar | Feb 2026 | 3,544 |
| `bayt_jobs_Qatar_12_May_2026.xlsx` | Qatar | May 2026 | 2,376 |
| `bayt_jobs_Saudi_Arabia_12_May_2026.xlsx` | Saudi Arabia | May 2026 | 8,236 |
| `bayt_jobs_UAE_12_May_2026.xlsx` | UAE | May 2026 | 9,923 |

**Total: ~25,959 job postings** across 3 GCC countries and 3 time periods.

Each posting contains 19 structured fields: Job Title, Company, Sector, Location, Salary, Employment Type, Career Level, Experience Required, Education Level, Skills, Qualifications, Language Requirements, Gender, and more.

**Naming convention** (drop any new file following this format — system picks it up automatically):
```
bayt_jobs_{Country}_{DD}_{Mon}_{YYYY}.xlsx
bayt_jobs_{Country}_AR_{DD}_{Mon}_{YYYY}.xlsx   ← Arabic portal version (optional)
```

---

## Project Structure

```
GCC-Job-Market-RAG/
│
├── 📄 app.py                  Main Streamlit application (Dashboard + Chat UI)
├── 📄 config.py               Global settings, API keys, model routing
├── 📄 data_loader.py          Data ingestion, normalisation, country/timeline parsing
├── 📄 analytics.py            Pandas statistics engine (salary, skills, sectors, trends)
├── 📄 sql_engine.py           Text-to-SQL layer (structured/counting queries)
├── 📄 vector_store.py         ChromaDB wrapper (semantic indexing + search)
├── 📄 rag_engine.py           Core RAG pipeline orchestrator (HyST-inspired)
├── 📄 build_index.py          Offline index builder (run before deploying)
├── 📄 requirements.txt        Python dependencies
│
├── 📁 data/                   Job posting Excel files (tracked via Git LFS)
│   ├── bayt_jobs_Qatar_22_Nov_2025.xlsx
│   ├── bayt_jobs_Qatar_22_Feb_2026.xlsx
│   ├── bayt_jobs_Qatar_12_May_2026.xlsx
│   ├── bayt_jobs_Saudi_Arabia_12_May_2026.xlsx
│   └── bayt_jobs_UAE_12_May_2026.xlsx
│
├── 📁 chroma_db/              Pre-built vector index (tracked via Git LFS)
│   ├── chroma.sqlite3         Main ChromaDB database (~170MB, in LFS)
│   ├── {collection-id}/       HNSW vector index files
│   └── _manifest.json         Tracks which files are indexed (by filename hash)
│
├── 📁 .streamlit/
│   └── secrets.toml.example  Template for API keys on Streamlit Cloud
│
├── .gitattributes             Git LFS tracking rules (*.sqlite3, *.bin)
├── .gitignore                 Excludes .env, __pycache__, venv
└── .env                       Local API keys (never committed)
```

---

## System Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DATA PIPELINE (offline)                      │
│                                                                       │
│  Excel Files → data_loader.py → Normalisation → ChromaDB + SQLite   │
│                (country, month)   (career, sector,  (vectors + rows) │
│                                    employment type)                   │
└─────────────────────────────────────────────────────────────────────┘
                              ↓ (pre-built, instant load)
┌─────────────────────────────────────────────────────────────────────┐
│                       QUERY PIPELINE (real-time)                     │
│                                                                       │
│  User Question                                                        │
│       │                                                               │
│       ▼                                                               │
│  [1] Query Decomposer (gpt-4o-mini)                                  │
│       Extracts: country filter, job title, timeline, sector           │
│       Classifies: ANALYTICAL / SEMANTIC / HYBRID                     │
│       │                                                               │
│       ├──────────────────────┬────────────────────────────┐          │
│       ▼                      ▼                            ▼          │
│  [2] SQL Layer          [3] Pandas Layer          [4] ChromaDB       │
│   (gpt-4o-mini)          (analytics.py)           (semantic search)  │
│   Counts, rankings,      Skills, salary,          Top-K similar      │
│   comparisons            experience stats         job postings       │
│       │                      │                            │          │
│       └──────────────────────┴────────────────────────────┘          │
│                              ▼                                        │
│                    [5] Context Assembly                               │
│                    SQL stats + Pandas stats + Retrieved postings      │
│                              ▼                                        │
│                    [6] LLM Generation (Fanar-C-2-27B)                │
│                    System prompt + context + user question            │
│                              ▼                                        │
│                    Streaming answer → Streamlit UI                    │
└─────────────────────────────────────────────────────────────────────┘
```

### The 3-Layer Retrieval (HyST-Inspired)

Inspired by the **HyST (2025)** paper on hybrid retrieval over semi-structured tabular data. Instead of keyword-based routing, the system uses intelligent query decomposition:

| Layer | Technology | Handles |
|---|---|---|
| **Layer 1 — SQL** | SQLite + GPT-4o-mini | Counts, rankings, averages, trend comparisons |
| **Layer 2 — Pandas** | pandas + analytics.py | Skills frequency, salary parsing, experience distribution |
| **Layer 3 — Semantic** | ChromaDB + all-MiniLM-L6-v2 | Job matching, descriptions, role-specific queries |

**Example routing:**
```
"How many Full-Time jobs in Feb 2026?"
    → ANALYTICAL → SQL layer → df[employment_norm=='Full-Time'][timeline=='Feb 2026'].count()
    → Answer: 940 ✅

"Find jobs matching my CV: 5 years Finance, SAP"
    → SEMANTIC → ChromaDB → cosine similarity search → top 15 postings
    → Answer: ranked job list with match analysis ✅

"What salary do Data Analysts earn in Qatar?"
    → HYBRID → both layers run → SQL gives stats, ChromaDB gives examples
    → Answer: avg salary + relevant job postings ✅
```

---

## Key Features

### 📊 Dashboard Tab
- **KPI Cards** — Total postings, countries, companies, month-over-month growth, avg salary
- **Dynamic Filters** — Country, Sector, Timeline (all derived from actual data, never hardcoded)
- **Month Comparison** — Select any two periods to compare; auto-detects available timelines
- **9 Chart Sections** — Postings by Sector, Salary Intelligence, Career Level, Employment Type, Top Skills, Experience & Workforce, Language & Location, Most Advertised Positions, Top Companies
- **Supply-Demand Insights** — Auto-computed insight cards + AI narrative generator
- **Country Comparison** — Auto-shows when multiple countries are loaded

### 💬 Chat Tab
- **Natural language Q&A** — Ask anything about the GCC job market
- **Streaming responses** — Token-by-token output like ChatGPT
- **Retrieval Transparency Panel** — Shows query type detected, layers used, confidence scores for each retrieved document
- **Answer Verification** — Cross-checks bot's numbers against pandas ground truth (✅ Match / ⚠️ Discrepancy)
- **Chat History** — Last 3 turns used as context for follow-up questions
- **Quick Question Buttons** — One-click sample questions in sidebar
- **CV Matching** — Describe your background, get matched jobs + skill gap analysis

### 🗂️ Sidebar
- **Dataset Dump Cards** — Toggle countries/periods on/off (auto-discovered from files)
- **File Upload** — Drop new Excel file → instant dashboard + chat update
- **Model Selector** — Switch between Fanar and OpenAI models per session
- **Index Status** — Shows if index is up to date

---

## LLM Architecture

The system uses **two separate LLM roles**:

```
Internal tasks (structured output required):
  Query Decomposer    →  gpt-4o-mini  (OpenAI)  → JSON output
  SQL Generator       →  gpt-4o-mini  (OpenAI)  → SQL query output

User-facing answer:
  Final Generation    →  Fanar-C-2-27B (Fanar)  → Streaming answer
  AI Insights         →  Fanar-C-2-27B (Fanar)  → Market narrative
```

**Why two models?**
- Internal steps need reliable structured output (JSON, SQL) → GPT-4o-mini is battle-tested
- User-facing answers benefit from Fanar's Arabic/Gulf-region awareness
- Users can switch the final answer model from the sidebar

**Available models (user-selectable):**
| Model | Provider | Best for |
|---|---|---|
| Fanar-C-2-27B | Fanar (Qatar) | Default, Arabic-aware, Gulf context |
| Fanar-C-1-8.7B | Fanar (Qatar) | Balanced speed/quality |
| Fanar-S-1-7B | Fanar (Qatar) | Fast responses |
| GPT-4o | OpenAI | Highest quality, complex analysis |
| GPT-4o Mini | OpenAI | Fast fallback |
| GPT-3.5 Turbo | OpenAI | Fastest fallback |

---

## Embeddings & Vector Search

**Model:** `sentence-transformers/all-MiniLM-L6-v2`
- 384-dimensional dense vectors
- ~90 MB model, runs locally (no API cost)
- Optimised for semantic similarity of short texts

**Document format** (what gets embedded per job posting):
```
Country: Qatar
Timeline: Feb 2026
Job Title: Senior Software Engineer
Company: Qatar Foundation
Sector: Technology
Location: Doha, Qatar
Career Level: Senior
Experience: 5+ years
Salary: 8000-12000 USD/month
Skills: Python; Machine Learning; AWS; Docker; TensorFlow
Description: We are looking for...
```

Country and Timeline are placed **first** in every document — this prevents the LLM from hallucinating wrong countries (e.g., "Riyadh, Qatar").

**Similarity scoring:**
```
Confidence = 1 - cosine_distance

Score 0.90–1.00  ██████████  Very relevant
Score 0.70–0.89  ████████░░  Relevant
Score 0.50–0.69  █████░░░░░  Loosely related
Score < 0.50     ██░░░░░░░░  Weak match
```

---

## Data Normalisation

Raw Bayt.com data has inconsistent field values. The system normalises using **substring matching** (not exact string match) to handle all variants:

**Employment Type:**
```
"Full-Time" / "full time" / "FULL-TIME" / "fulltime"  →  "Full-Time"
"Contract" / "CONTRACT" / "contract-based"             →  "Contract"
```

**Career Level:**
```
"Mid-Level" / "متوسط الخبرة" / "Consultant" / "Intermediate"  →  "Mid-Level"
"Management" / "Manager" / "Supervisory" / "إدارة"             →  "Manager"
"Senior Consultant" / "Sr." / "Senior Associate"               →  "Senior"
```

This was the root cause of wrong answers in the original system — the bot said "66 Mid-Level jobs" when the dashboard showed 110, because it only matched the exact string "Mid-Level" and missed all Arabic/variant entries.

---

## Deployment

### Local Development

```bash
# 1. Clone
git clone https://github.com/mhdfaizjabir/jobmarket_bot.git
cd jobmarket_bot

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create .env file
echo "OPENAI_API_KEY=sk-..." > .env
echo "FANAR_API_KEY=..." >> .env

# 4. Build vector index (one-time, ~10 minutes)
python build_index.py

# 5. Run
streamlit run app.py
```

### Adding New Data

```bash
# Drop new file in data/ folder following naming convention:
# bayt_jobs_{Country}_{DD}_{Mon}_{YYYY}.xlsx

# Incremental index — only embeds NEW file, not everything
python build_index.py

# Commit and push (LFS handles large files automatically)
git add data/ chroma_db/
git commit -m "Add UAE Mar 2027 data"
git push
```

### Streamlit Cloud Deployment

```
1. Push repo to GitHub (includes pre-built chroma_db/ via Git LFS)
2. Go to share.streamlit.io → New app
3. Connect GitHub repo → main → app.py
4. Add Secrets:
     OPENAI_API_KEY = "sk-..."
     FANAR_API_KEY  = "..."
5. Deploy → instant startup (index pre-loaded from LFS)
```

**Why instant on Streamlit Cloud:** The `chroma_db/` folder (pre-built vector index) is committed to GitHub via Git LFS. Streamlit Cloud downloads it on startup — no re-embedding needed. The manifest file tracks file hashes using filenames only (not absolute paths), so it works correctly across machines.

---

## File Modules — Detailed

### `config.py`
Central configuration. Defines:
- API keys (loaded from `.env`)
- `CHAT_MODEL` — default LLM for final answers (Fanar-C-2-27B)
- `INTERNAL_MODEL` — LLM for SQL/decomposition (gpt-4o-mini)
- `make_client(model)` — routes to Fanar or OpenAI based on `"fanar/"` prefix
- `build_system_prompt(countries, timelines, total)` — dynamic system prompt (never hardcoded months/countries)
- Country flags, colors, available models

### `data_loader.py`
- `load_all(data_dir)` — scans folder, loads all EN Excel files
- `parse_file_info(path)` — extracts country + timeline from filename
- `sort_timelines(list)` — chronological sort (not alphabetical)
- `norm_employment(val)` — substring normalisation for employment type
- `norm_career(val)` — substring normalisation for career level
- AR file merging — if Arabic portal file exists, extracts language/nationalization/remote signals

### `analytics.py`
Pure pandas. No LLM. All methods degrade gracefully if columns are missing.
- `AnalyticsEngine(df)` — wraps a filtered DataFrame
- `sector_stats()`, `skill_stats()`, `salary_stats()` — formatted text blocks for LLM context
- `career_level_stats()`, `employment_type_stats()` — use normalised columns
- `trend_comparison()` — month-over-month analysis

### `sql_engine.py`
- `SQLEngine(df)` — loads DataFrame into in-memory SQLite
- `_build_system(df)` — builds schema prompt dynamically (real timelines, countries, row counts)
- `get_context(question)` — generates SQL via gpt-4o-mini → runs it → returns formatted result
- Falls back to `""` silently if SQL generation fails

### `vector_store.py`
- `VectorStore()` — wraps ChromaDB persistent client
- `build_index(df, files)` — full rebuild (use when doc format changes)
- `build_index_incremental(df, files)` — only embeds new/changed files
- `needs_indexing(files)` — checks manifest version + file hashes
- `search(query, n, where)` — semantic search with optional metadata filter
- Manifest uses **filename keys** (not full paths) → works on any OS

### `rag_engine.py`
The brain. HyST-inspired pipeline:
1. `_decompose(question)` — LLM extracts filters + query type + analysis types
2. `_apply_filters(df, filters)` — applies structured filters including soft job_title matching
3. `_build_full_context(question)` — runs all 3 layers, assembles context
4. `answer(question, model)` — streams final LLM response
5. `get_retrieval_info(question)` — returns transparency data (layers used, scores)

### `build_index.py`
CLI script for offline index building. Run separately from the app.
```
python build_index.py          # incremental (new files only)
python build_index.py --full   # full rebuild (after format changes)
```

### `app.py`
Streamlit UI. Two tabs:
- **Dashboard** — 9 chart sections, all filter-responsive, supply-demand insights
- **Chat** — streaming Q&A, retrieval transparency, answer verification
Sidebar: dump cards, file upload, index status, model selector.

---

## Answer Verification System

After every LLM response, the system cross-checks numbers against pandas:

```
Bot says: "There are 940 Full-Time jobs in Feb 2026"
              ↓
Verifier: df[emp_norm=='Full-Time'][timeline=='Feb 2026'].count() = 940
              ↓
✅ Match  →  shown to user with green check

Bot says: "There are 1,200 Full-Time jobs in Feb 2026"
              ↓
Verifier: actual = 940
              ↓
⚠️ Discrepancy  →  shown with orange warning
```

Only checks numbers the bot explicitly mentions next to known labels (employment type, total postings). Correctly handles subset counts (e.g., "based on 34 IT postings") without false alarms.

---

## Retrieval Transparency

Every chat response shows an expandable panel:

```
🔍 Retrieval Process
─────────────────────────────────────────
Query Type:    HYBRID
Filters:       _country=Qatar, job_title=data analyst
Analysis:      salary, skills

Layers used:   SQL / Pandas, ChromaDB (semantic search)

Top 8 semantic matches:
  0.91 ██████████  Data Analyst · QNBFS · Feb 2026
  0.87 █████████░  Senior Data Analyst · Qatar Foundation · Nov 2025
  0.84 ████████░░  Business Intelligence Analyst · Ooredoo · May 2026
  ...

SQL result preview:
  SELECT AVG(_sal_mid) FROM jobs WHERE _country='Qatar'
  AND LOWER(job_title) LIKE '%data analyst%'
  → $3,200/month (n=12)
```

---

## GCC Context the System Knows

- Qatar, UAE, Saudi Arabia job market dynamics
- Qatarization / Emiratization / Saudization policies
- Qatar Vision 2030, Saudi Vision 2030
- GCC salary norms and transparency issues (~7% of postings show salary)
- Common employers: Qatar Energy, Qatar Foundation, Aramco, ADNOC, GEMS
- Language dynamics: Arabic/English requirements by sector
- Expat workforce dominance in Qatar and UAE

---

## Known Limitations

1. **Salary data is sparse** — only ~7% of postings on Bayt.com disclose salary. All salary stats are based on this subset.
2. **Data is a snapshot** — postings scraped at a specific date. Job market changes daily.
3. **Bayt.com coverage** — only covers jobs posted on Bayt.com, not the full GCC market.
4. **Arabic content** — bilingual signal extraction (nationalization %, remote work %) requires the corresponding `_AR_` file to be present.

---

## Research Foundation

This system draws on the following academic work:

| Paper | Contribution to this system |
|---|---|
| **HyST (2025)** — Hybrid Retrieval over Semi-Structured Tabular Data | Query decomposition into SQL + semantic layers rather than keyword routing |
| **NLP-based Job Market Analysis** | Skill extraction, sector classification methodology |
| **LLM Skill Extraction** | Structured extraction of skills from unstructured job descriptions |

---

## Team

| Role | Contributor |
|---|---|
| RAG System, Pipeline, UI | Mohammad Faiz Jabir |
| Data Collection & Preprocessing | Albaraa |
| Supervision | Dr. Hamdy |

**Institution:** Hamad Bin Khalifa University (HBKU) — QCRI Internship 2026

---

## Repository

🔗 **GitHub:** [github.com/mhdfaizjabir/jobmarket_bot](https://github.com/mhdfaizjabir/jobmarket_bot)

Data files and pre-built ChromaDB index are stored via **Git LFS** (Large File Storage) — no waiting for index build on deployment.
