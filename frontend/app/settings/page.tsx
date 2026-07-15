'use client';

import { useEffect, useState } from 'react';
import SiteHeader from '@/components/SiteHeader';
import { fetchModels, ModelOption } from '@/lib/api';
import { useTheme } from '@/lib/theme';
import { useLanguage } from '@/lib/i18n';
import { PREFERRED_MODEL_KEY } from '@/lib/preferences';

export default function SettingsPage() {
  const { theme, toggleTheme } = useTheme();
  const { lang, toggleLang } = useLanguage();
  const [models, setModels] = useState<ModelOption[]>([]);
  const [selected, setSelected] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetchModels()
      .then(({ models: opts, default: def }) => {
        setModels(opts);
        setSelected(localStorage.getItem(PREFERRED_MODEL_KEY) ?? def);
      })
      .catch(console.error);
  }, []);

  function handleModelChange(value: string) {
    setSelected(value);
    localStorage.setItem(PREFERRED_MODEL_KEY, value);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  }

  return (
    <div style={{ background: 'var(--bg)', color: 'var(--text)', minHeight: '100vh' }}>
      <SiteHeader />

      <main className="max-w-2xl mx-auto px-4 sm:px-6 py-16 sm:py-24">
        <h1 className="text-3xl sm:text-4xl font-extrabold mb-4">Settings</h1>
        <p className="text-sm leading-relaxed mb-10" style={{ color: 'var(--muted)' }}>
          Preferences are saved to this browser (no account needed) and take effect the next time
          you open the app.
        </p>

        {/* Appearance */}
        <section className="mb-8">
          <h2 className="text-sm font-bold uppercase tracking-wide mb-3" style={{ color: 'var(--muted)' }}>Appearance</h2>
          <div className="card flex items-center justify-between">
            <div>
              <div className="font-medium text-sm">Theme</div>
              <div className="text-xs" style={{ color: 'var(--muted)' }}>Currently {theme === 'dark' ? 'Dark' : 'Light'} mode</div>
            </div>
            <button onClick={toggleTheme}
              className="px-4 py-1.5 text-xs font-semibold rounded-md border transition hover:border-purple-500"
              style={{ color: 'var(--text)', borderColor: 'var(--border)' }}>
              {theme === 'dark' ? '☀️ Switch to Light' : '🌙 Switch to Dark'}
            </button>
          </div>
        </section>

        {/* Language */}
        <section className="mb-8">
          <h2 className="text-sm font-bold uppercase tracking-wide mb-3" style={{ color: 'var(--muted)' }}>Language</h2>
          <div className="card flex items-center justify-between">
            <div>
              <div className="font-medium text-sm">Interface language</div>
              <div className="text-xs" style={{ color: 'var(--muted)' }}>Currently {lang === 'en' ? 'English' : 'العربية'}</div>
            </div>
            <button onClick={toggleLang}
              className="px-4 py-1.5 text-xs font-semibold rounded-md border transition hover:border-purple-500"
              style={{ color: 'var(--text)', borderColor: 'var(--border)' }}>
              {lang === 'en' ? 'العربية' : 'English'}
            </button>
          </div>
        </section>

        {/* Model */}
        <section className="mb-8">
          <h2 className="text-sm font-bold uppercase tracking-wide mb-3" style={{ color: 'var(--muted)' }}>AI Model</h2>
          <div className="card flex flex-col gap-3">
            <div className="text-xs" style={{ color: 'var(--muted)' }}>
              Default model used when you open the chat assistant. You can still switch models
              per-conversation from the app sidebar.
            </div>
            <div className="flex flex-col gap-2">
              {models.length === 0 && <div className="text-xs" style={{ color: 'var(--muted)' }}>Loading models…</div>}
              {models.map(({ label, value }) => (
                <label key={value} className="flex items-center gap-2 cursor-pointer text-sm">
                  <input type="radio" name="model" value={value} checked={selected === value}
                    onChange={() => handleModelChange(value)} className="accent-purple-500" />
                  <span style={{ color: selected === value ? 'var(--text)' : 'var(--muted)' }}>{label}</span>
                </label>
              ))}
            </div>
            {saved && <div className="text-xs" style={{ color: 'var(--accent)' }}>Saved ✓</div>}
          </div>
        </section>

        {/* Data & privacy */}
        <section>
          <h2 className="text-sm font-bold uppercase tracking-wide mb-3" style={{ color: 'var(--muted)' }}>Data &amp; Privacy</h2>
          <div className="card flex flex-col gap-2 text-xs" style={{ color: 'var(--muted)' }}>
            <p>No account or login is required to use this platform.</p>
            <p>No cookies are set — your session id lives only in this browser tab.</p>
            <p>Chat sessions are kept in memory for up to 2 hours of inactivity, then discarded.</p>
          </div>
        </section>
      </main>
    </div>
  );
}
