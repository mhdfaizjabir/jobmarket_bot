'use client';

import { useEffect, useState } from 'react';
import SiteHeader from '@/components/SiteHeader';
import { API, fetchHealth } from '@/lib/api';
import { HealthResponse } from '@/lib/types';

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span className="inline-block w-2 h-2 rounded-full mr-2"
      style={{ background: ok ? '#22c55e' : '#ef4444' }} />
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="card flex flex-col gap-1">
      <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--muted)' }}>{label}</div>
      <div className="text-xl font-bold">{value}</div>
    </div>
  );
}

export default function AdminPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  useEffect(() => {
    let cancelled = false;

    function poll() {
      fetchHealth()
        .then((h) => {
          if (cancelled) return;
          setHealth(h);
          setError(null);
          setLastChecked(new Date());
        })
        .catch(() => {
          if (!cancelled) setError('Could not reach the backend /health endpoint.');
        });
    }

    poll();
    const interval = setInterval(poll, 10_000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  return (
    <div style={{ background: 'var(--bg)', color: 'var(--text)', minHeight: '100vh' }}>
      <SiteHeader />

      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-16 sm:py-24">
        <div className="flex items-baseline justify-between mb-2 flex-wrap gap-2">
          <h1 className="text-3xl sm:text-4xl font-extrabold">System Status</h1>
          {lastChecked && (
            <span className="text-xs" style={{ color: 'var(--muted)' }}>
              Updated {lastChecked.toLocaleTimeString()} · refreshes every 10s
            </span>
          )}
        </div>
        <p className="text-sm leading-relaxed mb-8" style={{ color: 'var(--muted)' }}>
          This page reads the same public <code>/health</code> endpoint anyone can query directly —
          no additional data is exposed. There is no authentication on this platform yet (see the{' '}
          <a href="/docs" className="underline">Security doc</a>), so nothing sensitive is shown here.
        </p>

        {error && (
          <div className="card mb-6" style={{ borderColor: '#ef4444', color: '#ef4444' }}>{error}</div>
        )}

        {health && (
          <>
            <div className="card flex items-center gap-2 mb-6">
              <StatusDot ok={health.status === 'ok'} />
              <span className="font-semibold">{health.status === 'ok' ? 'Operational' : health.status}</span>
              <span className="text-xs ml-auto" style={{ color: 'var(--muted)' }}>
                {health.environment} · v{health.version}
              </span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-6">
              <Stat label="Uptime" value={formatUptime(health.uptime_s)} />
              <Stat label="Postings loaded" value={health.postings.toLocaleString()} />
              <Stat label="Vectors indexed" value={health.vectors.toLocaleString()} />
              <Stat label="Active sessions" value={health.sessions.active_sessions} />
              <Stat label="Models available" value={health.models_available} />
              <Stat label="Memory (MB)" value={health.memory_mb != null ? Math.round(health.memory_mb) : '—'} />
            </div>

            <div className="card flex items-center justify-between mb-6">
              <div>
                <div className="font-medium text-sm">Qdrant vector store</div>
                <div className="text-xs" style={{ color: 'var(--muted)' }}>Default model: {health.model_configured ?? '—'}</div>
              </div>
              <div className="flex items-center text-sm font-semibold">
                <StatusDot ok={health.qdrant_status === 'ok'} />
                {health.qdrant_status}
              </div>
            </div>
          </>
        )}

        <a href={`${API}/metrics`} target="_blank" rel="noopener noreferrer"
          className="px-4 py-2 text-sm font-semibold rounded-md border transition hover:border-purple-500 inline-flex items-center gap-2"
          style={{ borderColor: 'var(--border)', color: 'var(--text)' }}>
          View raw Prometheus metrics ↗
        </a>
        <p className="text-xs mt-2" style={{ color: 'var(--muted)' }}>
          In production this is blocked at the nginx layer and only reachable from inside the
          deployment network — the link above works in local/dev only.
        </p>
      </main>
    </div>
  );
}
