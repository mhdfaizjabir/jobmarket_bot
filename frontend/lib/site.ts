// Shared, factual project metadata used across the About/Research/Docs pages.
// Sourced from README.md / PROJECT_SPEC.md / RAG/mcq_summary.txt — keep in sync
// if those change.

export const GITHUB_URL = 'https://github.com/AlbaraaAloush/ai-powered-job-market-intelligence';

// Country → flag emoji, shared by the sidebar and dashboard. Callers that also
// render an "All" option fall back to 🌍 for keys not listed here.
export const COUNTRY_FLAGS: Record<string, string> = {
  Qatar: '🇶🇦', UAE: '🇦🇪', 'Saudi Arabia': '🇸🇦',
  Bahrain: '🇧🇭', Kuwait: '🇰🇼', Oman: '🇴🇲',
};

export const TEAM = [
  { role: 'RAG System, Pipeline, UI, Evaluation', name: 'Mohammad Faiz Jabir' },
  { role: 'Data Collection & Preprocessing', name: 'Albaraa' },
  { role: 'Benchmark Design & Validation', name: 'Mentor / Supervisor' },
  { role: 'Supervision', name: 'Dr. Hamdy' },
];

export const RESEARCH_PAPERS = [
  { title: 'HyST (2025) — Hybrid Retrieval over Semi-Structured Tabular Data', contribution: 'Query decomposition into SQL + semantic layers' },
  { title: 'NLP-based Job Market Analysis', contribution: 'Skill extraction, sector classification' },
  { title: 'LLM Skill Extraction', contribution: 'Structured extraction from unstructured job descriptions' },
];

// RAG_Benchmark_Jobs_GCC_MCQ.xlsx run — see RAG/mcq_summary.txt
export const MCQ_BENCHMARK = {
  overall: { correct: 165, total: 200, pct: 82.5 },
  byLanguage: [
    { label: 'English', correct: 83, total: 100, pct: 83.0 },
    { label: 'Arabic', correct: 82, total: 100, pct: 82.0 },
  ],
  byCountry: [
    { label: 'Qatar', correct: 45, total: 59, pct: 76.3 },
    { label: 'Saudi Arabia', correct: 62, total: 72, pct: 86.1 },
    { label: 'UAE', correct: 58, total: 69, pct: 84.1 },
  ],
};

export const KNOWN_LIMITATIONS = [
  'Salary data is sparse — only ~7% of postings disclose salary. All salary stats are based on this subset.',
  'Data is a snapshot — postings scraped at specific dates. The job market changes daily.',
  'Source coverage is limited to Bayt.com and LinkedIn, not the full GCC market.',
  'Arabic bilingual enrichment requires a matching _AR_ file per Bayt EN dump; LinkedIn has no Arabic portal equivalent.',
];

export const TECH_STACK = [
  { layer: 'Frontend', detail: 'Next.js (App Router) + React, Tailwind CSS, Recharts' },
  { layer: 'Backend API', detail: 'FastAPI + Uvicorn, SlowAPI rate limiting' },
  { layer: 'LLM', detail: 'Fanar-C-2-27B (Arabic-first) with OpenAI as an alternate provider' },
  { layer: 'Embeddings', detail: 'paraphrase-multilingual-MiniLM-L12-v2 (sentence-transformers)' },
  { layer: 'Vector store', detail: 'Qdrant Cloud' },
  { layer: 'Structured query layer', detail: 'In-memory SQLite, populated per request from the active dataset' },
  { layer: 'Observability', detail: 'Prometheus (/metrics), structured JSON-shaped logs, Sentry + Langfuse hooks (enable via env keys)' },
  { layer: 'Deployment', detail: 'Docker Compose + nginx reverse proxy, GitHub Actions CI' },
];
