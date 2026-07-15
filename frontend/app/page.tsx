'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useTheme } from '@/lib/theme';
import { useLanguage } from '@/lib/i18n';

function FaqItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="card" style={{ cursor: 'pointer' }} onClick={() => setOpen(o => !o)}>
      <div className="flex items-center justify-between gap-4">
        <h3 className="font-semibold text-sm sm:text-base" style={{ color: 'var(--text)' }}>{q}</h3>
        <span style={{ color: 'var(--accent)' }} className="text-xl leading-none shrink-0">
          {open ? '−' : '+'}
        </span>
      </div>
      {open && (
        <p className="text-sm mt-3 leading-relaxed" style={{ color: 'var(--muted)' }}>{a}</p>
      )}
    </div>
  );
}

export default function LandingPage() {
  const { theme, toggleTheme } = useTheme();
  const { lang, toggleLang, t, dir } = useLanguage();

  const pipelineSteps = [
    { icon: '🌐', title: t('pipeline.step1Title'), desc: t('pipeline.step1Desc') },
    { icon: '📊', title: t('pipeline.step2Title'), desc: t('pipeline.step2Desc') },
    { icon: '🧠', title: t('pipeline.step3Title'), desc: t('pipeline.step3Desc') },
    { icon: '💬', title: t('pipeline.step4Title'), desc: t('pipeline.step4Desc') },
  ];

  const features = [
    { icon: '📈', title: t('features.item1Title'), desc: t('features.item1Desc') },
    { icon: '🤖', title: t('features.item2Title'), desc: t('features.item2Desc') },
    { icon: '🌍', title: t('features.item3Title'), desc: t('features.item3Desc') },
    { icon: '🌓', title: t('features.item4Title'), desc: t('features.item4Desc') },
  ];

  const faqs = [
    { q: t('faq.q1'), a: t('faq.a1') },
    { q: t('faq.q2'), a: t('faq.a2') },
    { q: t('faq.q3'), a: t('faq.a3') },
    { q: t('faq.q4'), a: t('faq.a4') },
  ];

  const arrow = dir === 'rtl' ? '←' : '→';

  return (
    <div style={{ background: 'var(--bg)', color: 'var(--text)', minHeight: '100vh' }}>

      {/* ── Nav ───────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-50 border-b backdrop-blur"
        style={{ borderColor: 'var(--border)', background: 'color-mix(in srgb, var(--bg) 85%, transparent)' }}>
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2 font-bold text-base sm:text-lg shrink-0">
            <span>🌍</span>
            <span>{t('nav.brand')}</span>
          </div>

          <nav className="hidden md:flex items-center gap-6 text-sm font-medium" style={{ color: 'var(--muted)' }}>
            <a href="#features" className="hover:opacity-80 transition">{t('nav.features')}</a>
            <a href="#pipeline" className="hover:opacity-80 transition">{t('nav.services')}</a>
            <a href="#faq" className="hover:opacity-80 transition">{t('nav.faq')}</a>
            <Link href="/research" className="hover:opacity-80 transition">{t('nav.research')}</Link>
            <Link href="/about" className="hover:opacity-80 transition">{t('nav.about')}</Link>
          </nav>

          <div className="flex items-center gap-2 shrink-0">
            <button onClick={toggleLang}
              className="px-3 py-1.5 text-xs font-semibold rounded-md border transition hover:border-purple-500"
              style={{ color: 'var(--text)', borderColor: 'var(--border)' }}
              title="EN / AR">
              {lang === 'en' ? 'العربية' : 'English'}
            </button>
            <button onClick={toggleTheme}
              className="px-3 py-1.5 text-xs font-semibold rounded-md border transition hover:border-purple-500"
              style={{ color: 'var(--text)', borderColor: 'var(--border)' }}
              title="Toggle theme">
              {theme === 'dark' ? '☀️' : '🌙'}
            </button>
            <Link href="/app"
              className="px-4 py-1.5 text-xs sm:text-sm font-semibold rounded-md transition hover:opacity-90"
              style={{ background: 'var(--accent)', color: '#ffffff' }}>
              {t('nav.getStarted')}
            </Link>
          </div>
        </div>
      </header>

      {/* ── Hero ──────────────────────────────────────────────────────── */}
      <section className="max-w-6xl mx-auto px-4 sm:px-6 pt-16 pb-20 sm:pt-24 sm:pb-28 text-center">
        <div className="inline-block px-4 py-1.5 rounded-full text-xs sm:text-sm font-semibold mb-6"
          style={{ background: 'var(--card)', border: '1px solid var(--border)', color: 'var(--accent)' }}>
          {t('hero.badge')}
        </div>
        <h1 className="text-3xl sm:text-5xl lg:text-6xl font-extrabold leading-tight mb-6 max-w-4xl mx-auto">
          {t('hero.title')}
        </h1>
        <p className="text-base sm:text-lg max-w-2xl mx-auto mb-10" style={{ color: 'var(--muted)' }}>
          {t('hero.subtitle')}
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
          <Link href="/app"
            className="px-6 py-3 rounded-lg font-semibold text-sm sm:text-base transition hover:opacity-90 w-full sm:w-auto"
            style={{ background: 'var(--accent)', color: '#ffffff' }}>
            {t('hero.cta')} {arrow}
          </Link>
          <a href="#pipeline"
            className="px-6 py-3 rounded-lg font-semibold text-sm sm:text-base border transition hover:border-purple-500 w-full sm:w-auto"
            style={{ borderColor: 'var(--border)', color: 'var(--text)' }}>
            {t('hero.ctaSecondary')}
          </a>
        </div>
      </section>

      {/* ── Trusted by / data sources ────────────────────────────────── */}
      <section className="max-w-6xl mx-auto px-4 sm:px-6 pb-16 sm:pb-20">
        <p className="text-center text-xs sm:text-sm font-semibold tracking-wide uppercase mb-8" style={{ color: 'var(--muted)' }}>
          {t('trusted.title')}
        </p>
        <div className="flex flex-wrap items-center justify-center gap-6 sm:gap-10">
          <div className="flex items-center justify-center rounded-xl p-4 sm:p-5" style={{ background: '#ffffff', border: '1px solid var(--border)' }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/bayt.jpg" alt="Bayt.com" className="h-8 sm:h-10 w-auto object-contain" />
          </div>
          <div className="flex items-center justify-center rounded-xl p-4 sm:p-5" style={{ background: '#ffffff', border: '1px solid var(--border)' }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/linkedin.webp" alt="LinkedIn" className="h-8 sm:h-10 w-auto object-contain" />
          </div>
          <div className="flex items-center justify-center rounded-xl p-4 sm:p-5" style={{ background: '#ffffff', border: '1px solid var(--border)' }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/Fanar.avif" alt="Fanar" className="h-8 sm:h-10 w-auto object-contain" />
          </div>
        </div>
      </section>

      {/* ── How it works / pipeline ──────────────────────────────────── */}
      <section id="pipeline" className="max-w-6xl mx-auto px-4 sm:px-6 py-16 sm:py-24">
        <div className="text-center mb-12 sm:mb-16">
          <h2 className="text-2xl sm:text-4xl font-extrabold mb-4">{t('pipeline.title')}</h2>
          <p className="text-sm sm:text-base max-w-xl mx-auto" style={{ color: 'var(--muted)' }}>{t('pipeline.subtitle')}</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 md:gap-4 items-stretch">
          {pipelineSteps.map((step, i) => (
            <div key={i} className="flex md:flex-col items-center md:items-stretch gap-4 md:gap-0">
              <div className="card flex-1 flex flex-col items-center text-center gap-3 h-full">
                <div className="w-12 h-12 rounded-xl flex items-center justify-center text-2xl"
                  style={{ background: 'var(--bg-alt)', border: '1px solid var(--border)' }}>
                  {step.icon}
                </div>
                <h3 className="font-bold text-sm sm:text-base">{step.title}</h3>
                <p className="text-xs sm:text-sm leading-relaxed" style={{ color: 'var(--muted)' }}>{step.desc}</p>
              </div>
              {i < pipelineSteps.length - 1 && (
                <div className="hidden md:flex items-center justify-center text-2xl shrink-0 px-1"
                  style={{ color: 'var(--border)' }}>
                  {arrow}
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* ── Features / services ──────────────────────────────────────── */}
      <section id="features" className="max-w-6xl mx-auto px-4 sm:px-6 py-16 sm:py-24">
        <div className="text-center mb-12 sm:mb-16">
          <h2 className="text-2xl sm:text-4xl font-extrabold mb-4">{t('features.title')}</h2>
          <p className="text-sm sm:text-base max-w-xl mx-auto" style={{ color: 'var(--muted)' }}>{t('features.subtitle')}</p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6">
          {features.map((f, i) => (
            <div key={i} className="card flex flex-col gap-3">
              <div className="w-12 h-12 rounded-xl flex items-center justify-center text-2xl"
                style={{ background: 'var(--bg-alt)', border: '1px solid var(--border)' }}>
                {f.icon}
              </div>
              <h3 className="font-bold text-sm sm:text-base">{f.title}</h3>
              <p className="text-xs sm:text-sm leading-relaxed" style={{ color: 'var(--muted)' }}>{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── FAQ ───────────────────────────────────────────────────────── */}
      <section id="faq" className="max-w-3xl mx-auto px-4 sm:px-6 py-16 sm:py-24">
        <div className="text-center mb-12">
          <h2 className="text-2xl sm:text-4xl font-extrabold">{t('faq.title')}</h2>
        </div>
        <div className="flex flex-col gap-4">
          {faqs.map((f, i) => (
            <FaqItem key={i} q={f.q} a={f.a} />
          ))}
        </div>
      </section>

      {/* ── Footer ────────────────────────────────────────────────────── */}
      <footer className="border-t" style={{ borderColor: 'var(--border)' }}>
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-10 flex flex-col gap-6">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-2 font-bold">
              <span>🌍</span>
              <span>{t('nav.brand')}</span>
            </div>
            <p className="text-xs sm:text-sm text-center" style={{ color: 'var(--muted)' }}>{t('footer.tagline')}</p>
          </div>
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-6 border-t" style={{ borderColor: 'var(--border)' }}>
            <nav className="flex items-center gap-4 text-xs sm:text-sm" style={{ color: 'var(--muted)' }}>
              <Link href="/about" className="hover:opacity-80 transition">{t('nav.about')}</Link>
              <Link href="/research" className="hover:opacity-80 transition">{t('nav.research')}</Link>
              <Link href="/docs" className="hover:opacity-80 transition">{t('nav.docs')}</Link>
            </nav>
            <p className="text-xs sm:text-sm" style={{ color: 'var(--muted)' }}>
              © {new Date().getFullYear()} · {t('footer.rights')}
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
