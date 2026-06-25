export interface DumpInfo {
  _dump_id: string;
  _country: string;
  _timeline: string;
  _dump_label: string;
  count: number;
  _source?: string;   // "Bayt" | "LinkedIn"
}

export interface DatasetsResponse {
  dumps: DumpInfo[];
  timelines: string[];
  sources?: string[];
}

export interface DashboardData {
  total: number;
  countries: string[];
  timelines: string[];
  kpi_mom: { t1: string; t2: string; c1: number; c2: number; pct: number } | null;
  sectors: { sector: string; count: number; _timeline?: string }[];
  career_levels: { level: string; count: number }[];
  employment_types: { type: string; count: number }[];
  salary: {
    coverage_pct: number;
    n_disclosed: number;
    avg_usd: number | null;
    distribution: { bracket: string; count: number }[];
    by_sector: { sector: string; avg_usd: number; count: number }[];
  };
  skills: { skill: string; count: number; pct: number }[];
  experience: { experience: string; count: number }[];
  company_size: { size: string; count: number }[];
  languages: { language: string; count: number }[];
  locations: { city: string; count: number }[];
  job_titles: { title: string; count: number }[];
  companies: { company: string; count: number }[];
  country_comparison: { country: string; count: number }[];
  trends: {
    t1: string; t2: string; n1: number; n2: number; overall_pct: number;
    growing: { sector: string; count_t1: number; count_t2: number; pct_change: number }[];
    declining: { sector: string; count_t1: number; count_t2: number; pct_change: number }[];
  } | null;
}

export interface SemanticHit {
  title: string;
  company: string;
  sector: string;
  timeline: string;
  country: string;
  score: number;
}

export interface RetrievalInfo {
  decomposed: {
    filters: Record<string, string>;
    semantic_query: string;
    needs_aggregation: boolean;
    analysis_types: string[];
    resolved_question: string;
  };
  needs_agg: boolean;
  layers_used: string[];
  sql_snippet: string;
  semantic_hits: SemanticHit[];
}

export interface Message {
  role: 'user' | 'assistant';
  content: string;
  streaming?: boolean;
  retrieval?: RetrievalInfo;
}
