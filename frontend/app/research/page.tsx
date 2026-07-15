'use client';

import SiteHeader from '@/components/SiteHeader';
import { KNOWN_LIMITATIONS, MCQ_BENCHMARK, RESEARCH_PAPERS, TECH_STACK } from '@/lib/site';

function Bar({ pct }: { pct: number }) {
  return (
    <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--bg-alt)' }}>
      <div className="h-full rounded-full" style={{ width: `${pct}%`, background: 'var(--accent)' }} />
    </div>
  );
}

function ScoreRow({ label, correct, total, pct }: { label: string; correct: number; total: number; pct: number }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between text-sm">
        <span style={{ color: 'var(--text)' }}>{label}</span>
        <span style={{ color: 'var(--muted)' }}>{correct}/{total} · {pct.toFixed(1)}%</span>
      </div>
      <Bar pct={pct} />
    </div>
  );
}

export default function ResearchPage() {
  return (
    <div style={{ background: 'var(--bg)', color: 'var(--text)', minHeight: '100vh' }}>
      <SiteHeader />

      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-16 sm:py-24">
        <h1 className="text-3xl sm:text-4xl font-extrabold mb-4">Research</h1>
        <p className="text-sm sm:text-base leading-relaxed mb-12" style={{ color: 'var(--muted)' }}>
          This page documents the methodology, architecture, and evaluation behind the platform —
          the &ldquo;how&rdquo; and &ldquo;how well&rdquo; underneath the dashboard and chat assistant.
        </p>

        {/* Methodology */}
        <section className="mb-12">
          <h2 className="text-xl font-bold mb-3">Methodology</h2>
          <p className="text-sm leading-relaxed mb-3" style={{ color: 'var(--muted)' }}>
            Every question is decomposed by an LLM call into structured filters (country, timeline,
            sector, career level…) plus a semantic query. From there, up to three retrieval layers
            run in parallel and feed a single grounded context into the final answer:
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="card">
              <div className="font-semibold text-sm mb-1">SQL layer</div>
              <p className="text-xs leading-relaxed" style={{ color: 'var(--muted)' }}>
                Text-to-SQL against an in-memory SQLite copy of the active dataset — for counting,
                aggregation, and exact-match questions.
              </p>
            </div>
            <div className="card">
              <div className="font-semibold text-sm mb-1">Analytics layer</div>
              <p className="text-xs leading-relaxed" style={{ color: 'var(--muted)' }}>
                Pandas aggregation for statistics SQL doesn&apos;t cover — skills frequency, salary
                distribution, language breakdowns.
              </p>
            </div>
            <div className="card">
              <div className="font-semibold text-sm mb-1">Semantic layer</div>
              <p className="text-xs leading-relaxed" style={{ color: 'var(--muted)' }}>
                Multilingual embedding search over Qdrant Cloud for open-ended, descriptive
                questions about specific postings.
              </p>
            </div>
          </div>
        </section>

        {/* Architecture */}
        <section className="mb-12">
          <h2 className="text-xl font-bold mb-3">Architecture</h2>
          <p className="text-sm leading-relaxed mb-3" style={{ color: 'var(--muted)' }}>
            UI-driven filters (e.g. clicking a sector on the dashboard) and LLM-inferred filters
            (e.g. &ldquo;entry level jobs in Qatar&rdquo; typed into chat) both flow through a single registry
            (<code>filter_registry.py</code>) so the dashboard and chatbot can never silently
            disagree about what data is in scope. Full request/data flow diagrams are in the{' '}
            <a href="/docs" className="underline">Documentation</a> page.
          </p>
        </section>

        {/* Tech stack */}
        <section className="mb-12">
          <h2 className="text-xl font-bold mb-4">Technology Stack</h2>
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <tbody>
                {TECH_STACK.map((row) => (
                  <tr key={row.layer} className="border-t first:border-t-0" style={{ borderColor: 'var(--border)' }}>
                    <td className="py-2 pr-4 font-semibold whitespace-nowrap align-top">{row.layer}</td>
                    <td className="py-2" style={{ color: 'var(--muted)' }}>{row.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Evaluation */}
        <section className="mb-12">
          <h2 className="text-xl font-bold mb-2">Evaluation &amp; Benchmarks</h2>
          <p className="text-sm leading-relaxed mb-4" style={{ color: 'var(--muted)' }}>
            A 200-question multiple-choice benchmark (bilingual EN/AR, sourced across all three
            countries) checks whether the assistant selects the factually correct option grounded
            in the underlying data. Answers are additionally cross-checked against a SQL ground
            truth and a numeric-claim verifier in a separate, harder evaluation pass.
          </p>
          <div className="card flex flex-col gap-4">
            <ScoreRow label="Overall accuracy" {...MCQ_BENCHMARK.overall} />
            <hr style={{ borderColor: 'var(--border)' }} />
            <div className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--muted)' }}>By language</div>
            {MCQ_BENCHMARK.byLanguage.map((row) => <ScoreRow key={row.label} {...row} />)}
            <hr style={{ borderColor: 'var(--border)' }} />
            <div className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--muted)' }}>By country</div>
            {MCQ_BENCHMARK.byCountry.map((row) => <ScoreRow key={row.label} {...row} />)}
          </div>
        </section>

        {/* Limitations */}
        <section className="mb-12">
          <h2 className="text-xl font-bold mb-4">Known Limitations</h2>
          <ul className="flex flex-col gap-2">
            {KNOWN_LIMITATIONS.map((l, i) => (
              <li key={i} className="text-sm leading-relaxed flex gap-2" style={{ color: 'var(--muted)' }}>
                <span style={{ color: 'var(--accent)' }}>—</span>
                <span>{l}</span>
              </li>
            ))}
          </ul>
        </section>

        {/* Future work */}
        <section className="mb-12">
          <h2 className="text-xl font-bold mb-4">Future Work</h2>
          <ul className="flex flex-col gap-2">
            {[
              'Hybrid retrieval (BM25 + vector fusion) and cross-encoder reranking, to improve recall on keyword-heavy queries.',
              'Redis-backed rate limiting and session storage, to support horizontal scaling beyond a single replica.',
              'OpenTelemetry distributed tracing, once the deployment spans more than one service.',
              'Additional explicit dashboard filters (employment type, experience level, company, language, salary range) — the registry already supports adding these; on hold pending scope approval.',
            ].map((item, i) => (
              <li key={i} className="text-sm leading-relaxed flex gap-2" style={{ color: 'var(--muted)' }}>
                <span style={{ color: 'var(--accent)' }}>→</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </section>

        {/* Research foundation */}
        <section>
          <h2 className="text-xl font-bold mb-4">Research Foundation</h2>
          <div className="card overflow-x-auto mb-3">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ color: 'var(--muted)' }} className="text-left">
                  <th className="pb-2 pr-4 font-semibold">Paper</th>
                  <th className="pb-2 font-semibold">Contribution</th>
                </tr>
              </thead>
              <tbody>
                {RESEARCH_PAPERS.map((p) => (
                  <tr key={p.title} className="border-t" style={{ borderColor: 'var(--border)' }}>
                    <td className="py-2 pr-4 font-medium align-top">{p.title}</td>
                    <td className="py-2" style={{ color: 'var(--muted)' }}>{p.contribution}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs" style={{ color: 'var(--muted)' }}>
            No external publications yet — this internship deliverable is the current output of the work.
          </p>
        </section>
      </main>
    </div>
  );
}
