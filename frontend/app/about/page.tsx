'use client';

import Link from 'next/link';
import SiteHeader from '@/components/SiteHeader';
import { GITHUB_URL, TEAM } from '@/lib/site';

export default function AboutPage() {
  return (
    <div style={{ background: 'var(--bg)', color: 'var(--text)', minHeight: '100vh' }}>
      <SiteHeader />

      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-16 sm:py-24">
        <h1 className="text-3xl sm:text-4xl font-extrabold mb-4">About</h1>
        <p className="text-sm sm:text-base leading-relaxed mb-10" style={{ color: 'var(--muted)' }}>
          The GCC Job Market Intelligence Platform is a conversational AI assistant and analytics
          dashboard built over ~30,000 real job postings from Bayt.com and LinkedIn across Qatar,
          Saudi Arabia, and the UAE. It combines structured (SQL/pandas) analytics with semantic
          search over a vector database, so questions can be answered with grounded, citable data
          rather than free-form generation.
        </p>

        <section className="mb-12">
          <h2 className="text-xl font-bold mb-2">Institution</h2>
          <p className="text-sm leading-relaxed" style={{ color: 'var(--muted)' }}>
            Built at <strong style={{ color: 'var(--text)' }}>Hamad Bin Khalifa University (HBKU)</strong> as
            part of a QCRI Internship (2026).
          </p>
        </section>

        <section className="mb-12">
          <h2 className="text-xl font-bold mb-4">Team</h2>
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ color: 'var(--muted)' }} className="text-left">
                  <th className="pb-2 pr-4 font-semibold">Role</th>
                  <th className="pb-2 font-semibold">Contributor</th>
                </tr>
              </thead>
              <tbody>
                {TEAM.map((row) => (
                  <tr key={row.role} className="border-t" style={{ borderColor: 'var(--border)' }}>
                    <td className="py-2 pr-4" style={{ color: 'var(--muted)' }}>{row.role}</td>
                    <td className="py-2 font-medium">{row.name}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="mb-12">
          <h2 className="text-xl font-bold mb-4">Contact &amp; Source</h2>
          <div className="card flex flex-col gap-3">
            <p className="text-sm leading-relaxed" style={{ color: 'var(--muted)' }}>
              This project is open source. Bug reports, questions, and contributions are welcome
              through the GitHub repository. Security issues should go through the disclosure
              policy at <code>/.well-known/security.txt</code> rather than a public issue.
            </p>
            <div className="flex flex-wrap gap-3">
              <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer"
                className="px-4 py-2 text-sm font-semibold rounded-md transition hover:opacity-90 inline-flex items-center gap-2"
                style={{ background: 'var(--accent)', color: '#ffffff' }}>
                GitHub Repository ↗
              </a>
              <Link href="/research"
                className="px-4 py-2 text-sm font-semibold rounded-md border transition hover:border-purple-500 inline-flex items-center gap-2"
                style={{ borderColor: 'var(--border)', color: 'var(--text)' }}>
                Research &amp; Methodology
              </Link>
              <Link href="/docs"
                className="px-4 py-2 text-sm font-semibold rounded-md border transition hover:border-purple-500 inline-flex items-center gap-2"
                style={{ borderColor: 'var(--border)', color: 'var(--text)' }}>
                Documentation
              </Link>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
