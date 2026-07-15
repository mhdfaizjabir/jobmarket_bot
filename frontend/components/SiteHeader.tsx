'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useTheme } from '@/lib/theme';
import { useLanguage } from '@/lib/i18n';

const NAV_ITEMS = [
  { href: '/about', key: 'nav.about' },
  { href: '/research', key: 'nav.research' },
  { href: '/docs', key: 'nav.docs' },
] as const;

export default function SiteHeader() {
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();
  const { lang, toggleLang, t } = useLanguage();

  return (
    <header className="sticky top-0 z-50 border-b backdrop-blur"
      style={{ borderColor: 'var(--border)', background: 'color-mix(in srgb, var(--bg) 85%, transparent)' }}>
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
        <Link href="/" className="flex items-center gap-2 font-bold text-base sm:text-lg shrink-0" style={{ color: 'var(--text)' }}>
          <span>🌍</span>
          <span>{t('nav.brand')}</span>
        </Link>

        <nav className="hidden md:flex items-center gap-6 text-sm font-medium">
          <Link href="/app"
            className="hover:opacity-80 transition"
            style={{ color: pathname === '/app' ? 'var(--text)' : 'var(--muted)' }}>
            {t('app.dashboard')}
          </Link>
          {NAV_ITEMS.map(item => (
            <Link key={item.href} href={item.href}
              className="hover:opacity-80 transition"
              style={{ color: pathname === item.href ? 'var(--text)' : 'var(--muted)' }}>
              {t(item.key)}
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-2 shrink-0">
          <button onClick={toggleLang}
            aria-label="Switch language (English / Arabic)"
            className="px-3 py-1.5 text-xs font-semibold rounded-md border transition hover:border-purple-500"
            style={{ color: 'var(--text)', borderColor: 'var(--border)' }}
            title="EN / AR">
            {lang === 'en' ? 'العربية' : 'English'}
          </button>
          <button onClick={toggleTheme}
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            className="px-3 py-1.5 text-xs font-semibold rounded-md border transition hover:border-purple-500"
            style={{ color: 'var(--text)', borderColor: 'var(--border)' }}
            title="Toggle theme">
            <span aria-hidden="true">{theme === 'dark' ? '☀️' : '🌙'}</span>
          </button>
          <Link href="/app"
            className="px-4 py-1.5 text-xs sm:text-sm font-semibold rounded-md transition hover:opacity-90"
            style={{ background: 'var(--accent)', color: '#ffffff' }}>
            {t('nav.getStarted')}
          </Link>
        </div>
      </div>
    </header>
  );
}
