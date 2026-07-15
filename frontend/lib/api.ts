import { DashboardData, DatasetsResponse, HealthResponse, RetrievalInfo } from './types';

// `??` (not `||`) so an explicitly-empty NEXT_PUBLIC_API_URL means "same origin"
// — the production nginx setup serves the API under the same host at /api/*,
// so the Docker build passes NEXT_PUBLIC_API_URL="" to get relative URLs.
// Unset (local dev without Docker) still falls back to the local backend.
export const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export async function fetchDatasets(): Promise<DatasetsResponse> {
  const r = await fetch(`${API}/api/datasets`);
  if (!r.ok) throw new Error('Failed to fetch datasets');
  return r.json();
}

// One field per RAG/filter_registry.py entry, mirrored in server.py's
// get_dashboard() query params — plus country/timeline, which stay on the
// dump_ids selection mechanism rather than the explicit_filters registry.
export interface DashboardParams {
  dumps: string[];
  country?: string;
  timeline?: string;
  sector?: string;
  employment_type?: string;
  career_level?: string;
  company?: string;
  experience?: string;
  salary_bucket?: string;
}

function dashboardQuery(params: DashboardParams): URLSearchParams {
  const q = new URLSearchParams();
  if (params.dumps.length) q.set('dumps', params.dumps.join(','));
  const named: (keyof DashboardParams)[] = [
    'country', 'timeline', 'sector', 'employment_type', 'career_level', 'company', 'experience', 'salary_bucket',
  ];
  for (const key of named) {
    const value = params[key];
    if (typeof value === 'string' && value && value !== 'All') q.set(key, value);
  }
  return q;
}

export async function fetchDashboard(params: DashboardParams): Promise<DashboardData> {
  const r = await fetch(`${API}/api/dashboard?${dashboardQuery(params)}`);
  if (!r.ok) throw new Error('Failed to fetch dashboard data');
  return r.json();
}

// Backs each chart's download-as-Excel button. A plain navigable URL (not a
// fetch+blob) so the browser handles the Content-Disposition: attachment
// response as a normal download, no CORS/blob plumbing needed.
export function dashboardExportUrl(chart: string, params: DashboardParams): string {
  const q = dashboardQuery(params);
  q.set('chart', chart);
  return `${API}/api/dashboard/export?${q}`;
}

export interface ModelOption {
  label: string;
  value: string;
}

export async function fetchModels(): Promise<{ models: ModelOption[]; default: string }> {
  const r = await fetch(`${API}/api/models`);
  if (!r.ok) throw new Error('Failed to fetch models');
  return r.json();
}

export async function fetchHealth(): Promise<HealthResponse> {
  const r = await fetch(`${API}/health`);
  if (!r.ok) throw new Error('Failed to fetch health');
  return r.json();
}

export async function createSession(): Promise<string> {
  const r = await fetch(`${API}/api/session`, { method: 'POST' });
  const data = await r.json();
  return data.session_id;
}

export async function clearSession(sessionId: string): Promise<void> {
  await fetch(`${API}/api/session/${sessionId}`, { method: 'DELETE' });
}

// Typed stream events from the server
export type StreamEvent =
  | { type: 'retrieval'; info: RetrievalInfo }
  | { type: 'token'; token: string }
  | { type: 'done' };

export async function* streamChat(
  question: string,
  sessionId: string,
  model: string,
  dumpIds: string[],
  signal?: AbortSignal,
  filters?: Record<string, string>,
): AsyncGenerator<StreamEvent> {
  const r = await fetch(`${API}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, session_id: sessionId, model, dump_ids: dumpIds, filters: filters ?? {} }),
    signal,
  });

  if (!r.ok) throw new Error(`Chat error: ${r.status}`);
  if (!r.body) return;

  const reader  = r.body.getReader();
  const decoder = new TextDecoder();
  let   buf     = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop() ?? '';

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const raw = line.slice(6).trim();
      if (raw === '[DONE]') { yield { type: 'done' }; return; }
      try {
        const parsed = JSON.parse(raw);
        if (parsed.type === 'retrieval') yield { type: 'retrieval', info: parsed.info };
        else if (parsed.type === 'token' && parsed.token) yield { type: 'token', token: parsed.token };
      } catch { /* skip partial */ }
    }
  }
}
