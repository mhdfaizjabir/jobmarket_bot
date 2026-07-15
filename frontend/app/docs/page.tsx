'use client';

import SiteHeader from '@/components/SiteHeader';
import { GITHUB_URL } from '@/lib/site';

const DOC_LINKS = [
  { title: 'Architecture', file: 'ARCHITECTURE.md', desc: 'Request flow, RAG pipeline, filter flow, Qdrant/SQL flow, error handling.' },
  { title: 'API Reference', file: 'API.md', desc: 'REST + streaming endpoints, request/response shapes.' },
  { title: 'Deployment', file: 'DEPLOYMENT.md', desc: 'Local dev, Docker, production compose, environment separation.' },
  { title: 'Security', file: 'SECURITY.md', desc: 'Threat model, implemented controls, residual risks, disclosure policy.' },
  { title: 'Observability', file: 'OBSERVABILITY.md', desc: 'Prometheus metrics, Sentry, Langfuse tracing.' },
  { title: 'Runbook', file: 'RUNBOOK.md', desc: 'Operational procedures — start/stop, failure scenarios, routine ops.' },
  { title: 'Project Spec', file: 'PROJECT_SPEC.md', desc: 'Living spec + sprint log — what shipped and why.' },
];

export default function DocsPage() {
  return (
    <div style={{ background: 'var(--bg)', color: 'var(--text)', minHeight: '100vh' }}>
      <SiteHeader />

      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-16 sm:py-24">
        <h1 className="text-3xl sm:text-4xl font-extrabold mb-4">Documentation</h1>
        <p className="text-sm sm:text-base leading-relaxed mb-10" style={{ color: 'var(--muted)' }}>
          Full technical documentation lives as Markdown in the repository, kept next to the code
          it describes so it doesn&apos;t drift. Linked here rather than duplicated.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {DOC_LINKS.map((doc) => (
            <a key={doc.file} href={`${GITHUB_URL}/blob/main/${doc.file}`}
              target="_blank" rel="noopener noreferrer"
              className="card flex flex-col gap-1.5 transition hover:border-purple-500"
              style={{ borderColor: 'var(--border)' }}>
              <div className="flex items-center justify-between">
                <span className="font-semibold text-sm">{doc.title}</span>
                <span style={{ color: 'var(--accent)' }}>↗</span>
              </div>
              <p className="text-xs leading-relaxed" style={{ color: 'var(--muted)' }}>{doc.desc}</p>
              <code className="text-xs mt-1" style={{ color: 'var(--muted)' }}>{doc.file}</code>
            </a>
          ))}
        </div>
      </main>
    </div>
  );
}
