import { DashboardData, DatasetsResponse, RetrievalInfo } from './types';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function fetchDatasets(): Promise<DatasetsResponse> {
  const r = await fetch(`${API}/api/datasets`);
  if (!r.ok) throw new Error('Failed to fetch datasets');
  return r.json();
}

export interface DashboardParams {
  dumps: string[];
  country?: string;
  sector?: string;
  timeline?: string;
}

export async function fetchDashboard(params: DashboardParams): Promise<DashboardData> {
  const q = new URLSearchParams();
  if (params.dumps.length) q.set('dumps', params.dumps.join(','));
  if (params.country  && params.country  !== 'All') q.set('country',  params.country);
  if (params.sector   && params.sector   !== 'All') q.set('sector',   params.sector);
  if (params.timeline && params.timeline !== 'All') q.set('timeline', params.timeline);
  const r = await fetch(`${API}/api/dashboard?${q}`);
  if (!r.ok) throw new Error('Failed to fetch dashboard data');
  return r.json();
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
): AsyncGenerator<StreamEvent> {
  const r = await fetch(`${API}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, session_id: sessionId, model, dump_ids: dumpIds }),
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
