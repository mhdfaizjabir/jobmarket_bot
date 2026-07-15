'use client';

import { Suspense, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { fetchDatasets, fetchModels, ModelOption } from '@/lib/api';
import { DumpInfo } from '@/lib/types';
import Sidebar from '@/components/Sidebar';
import Dashboard, { DASHBOARD_FILTER_KEYS } from '@/components/Dashboard';
import Chat from '@/components/Chat';
import { useTheme } from '@/lib/theme';
import { useLanguage } from '@/lib/i18n';
import { PREFERRED_MODEL_KEY } from '@/lib/preferences';

function LoadingScreen() {
  return (
    <div className="flex items-center justify-center h-screen">
      <div className="text-purple-400 animate-pulse">Loading GCC Job Market Intelligence…</div>
    </div>
  );
}

export default function AppPage() {
  // useSearchParams requires a Suspense boundary at build time — see
  // node_modules/next/dist/docs/01-app/03-api-reference/04-functions/use-search-params.md.
  return (
    <Suspense fallback={<LoadingScreen />}>
      <AppPageInner />
    </Suspense>
  );
}

// Builds the shareable query string for the current view — omits anything
// that's already the default so a plain "everything selected" view keeps a
// clean URL, and only deviations (a subset of dumps, an active filter, the
// chat tab, a non-default model) show up as params.
function buildShareQuery(opts: {
  selected: string[]; allDumpIds: string[]; filters: Record<string, string>;
  tab: 'dashboard' | 'chat'; model: string; defaultModel: string;
}): URLSearchParams {
  const q = new URLSearchParams();
  if (opts.selected.length !== opts.allDumpIds.length) {
    q.set('d', opts.selected.join(','));
  }
  for (const key of DASHBOARD_FILTER_KEYS) {
    const v = opts.filters[key];
    if (v) q.set(key, v);
  }
  if (opts.tab !== 'dashboard') q.set('tab', opts.tab);
  if (opts.model && opts.model !== opts.defaultModel) q.set('m', opts.model);
  return q;
}

function AppPageInner() {
  const [dumps,     setDumps]     = useState<DumpInfo[]>([]);
  const [timelines, setTimelines] = useState<string[]>([]);
  const [selected,  setSelected]  = useState<string[]>([]);
  const [models,    setModels]    = useState<ModelOption[]>([]);
  const [model,     setModel]     = useState('');
  const [defaultModel, setDefaultModel] = useState('');
  const [tab,       setTab]       = useState<'dashboard' | 'chat'>('dashboard');
  const [sidebarOpen, setSidebar] = useState(true);
  const [loading,   setLoading]   = useState(true);
  const [copied,    setCopied]    = useState(false);

  // Single source of truth for every UI-driven "explicit" filter (sector today,
  // more later — see RAG/filter_registry.py). Both Dashboard and Chat read the
  // same object, so they can never disagree about what's active.
  const [filters, setFilters] = useState<Record<string, string>>({});

  function handleFilterChange(key: string, value: string | null) {
    setFilters(prev => {
      if (!value || value === 'All') {
        const next = { ...prev };
        delete next[key];
        return next;
      }
      return { ...prev, [key]: value };
    });
  }

  const { theme, toggleTheme } = useTheme();
  const { lang, toggleLang, t } = useLanguage();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Only true once initial state has been reconciled with the URL (or defaulted)
  // — guards the URL-sync effect below from firing with half-initialized state
  // and clobbering a shared link's params before they've been applied.
  const hydrated = useRef(false);

  useEffect(() => {
    Promise.all([fetchDatasets(), fetchModels()])
      .then(([datasets, modelData]) => {
        setDumps(datasets.dumps);
        setTimelines(datasets.timelines);
        setModels(modelData.models);
        setDefaultModel(modelData.default);

        // Restore state from a shared link's query string, captured once at
        // mount (deliberately not a dependency — re-running this on every
        // searchParams change would fight the URL-sync effect below).
        const allIds = datasets.dumps.map(d => d._dump_id);
        const dParam = searchParams.get('d');
        const sharedIds = dParam ? dParam.split(',').filter(id => allIds.includes(id)) : [];
        setSelected(sharedIds.length > 0 ? sharedIds : allIds);

        const sharedFilters: Record<string, string> = {};
        for (const key of DASHBOARD_FILTER_KEYS) {
          const v = searchParams.get(key);
          if (v) sharedFilters[key] = v;
        }
        setFilters(sharedFilters);

        setTab(searchParams.get('tab') === 'chat' ? 'chat' : 'dashboard');

        const mParam = searchParams.get('m');
        const preferred = localStorage.getItem(PREFERRED_MODEL_KEY);
        const sharedModelValid = mParam && modelData.models.some(m => m.value === mParam);
        const preferredValid = preferred && modelData.models.some(m => m.value === preferred);
        setModel(sharedModelValid ? mParam! : preferredValid ? preferred! : modelData.default);

        hydrated.current = true;
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the URL in sync with the current view so it's always shareable as-is,
  // not just via the explicit copy button.
  useEffect(() => {
    if (!hydrated.current || dumps.length === 0) return;
    const q = buildShareQuery({
      selected, allDumpIds: dumps.map(d => d._dump_id), filters, tab, model, defaultModel,
    });
    const qs = q.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, filters, tab, model, dumps.length]);

  function handleShare() {
    const q = buildShareQuery({
      selected, allDumpIds: dumps.map(d => d._dump_id), filters, tab, model, defaultModel,
    });
    const qs = q.toString();
    const url = `${window.location.origin}${pathname}${qs ? `?${qs}` : ''}`;
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    }).catch(console.error);
  }

  function handleModelChange(value: string) {
    setModel(value);
    localStorage.setItem(PREFERRED_MODEL_KEY, value);
  }

  function toggleDump(id: string) {
    setSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  }

  // Clicking a timeline pill selects all dumps for that month (or all dumps for "All")
  function handleTimelineSelect(tl: string) {
    if (tl === 'All') {
      setSelected(dumps.map(d => d._dump_id));
    } else {
      setSelected(dumps.filter(d => d._timeline === tl).map(d => d._dump_id));
    }
  }

  // Derive active timeline — single shared month → that month; mixed → "All"
  const selectedTLs = [...new Set(dumps.filter(d => selected.includes(d._dump_id)).map(d => d._timeline))];
  const activeTimeline = selectedTLs.length === 1 ? selectedTLs[0] : 'All';

  // Clicking a country tab selects all dumps for that country (or all dumps for "All")
  function handleCountrySelect(country: string) {
    if (country === 'All') {
      setSelected(dumps.map(d => d._dump_id));
    } else {
      setSelected(dumps.filter(d => d._country === country).map(d => d._dump_id));
    }
  }

  // Derive active country — single country across all selected dumps → that country; mixed → "All"
  const selectedCountries = [...new Set(dumps.filter(d => selected.includes(d._dump_id)).map(d => d._country))];
  const activeCountry = selectedCountries.length === 1 ? selectedCountries[0] : 'All';

  // All countries available (for tabs — always shown regardless of selection)
  const allCountries = [...new Set(dumps.map(d => d._country))].sort();

  // Total job counts per country across ALL dumps (stable reference shown on tabs)
  const allCountryCounts: Record<string, number> = {};
  dumps.forEach(d => { allCountryCounts[d._country] = (allCountryCounts[d._country] ?? 0) + d.count; });

  if (loading) {
    return <LoadingScreen />;
  }

  return (
    <div className="flex h-screen overflow-hidden">

      <Sidebar
        dumps={dumps}
        timelines={timelines}
        selected={selected}
        model={model}
        models={models}
        isOpen={sidebarOpen}
        onToggle={toggleDump}
        onSelectAll={() => setSelected(dumps.map(d => d._dump_id))}
        onClearAll={() => setSelected([])}
        onModelChange={handleModelChange}
        onCollapse={() => setSidebar(o => !o)}
      />

      <div className="flex-1 flex flex-col overflow-hidden">

        {/* Top bar */}
        <header className="flex items-center gap-0 px-4 pt-3 pb-0 border-b shrink-0"
                style={{ borderColor: 'var(--border)' }}>
          {!sidebarOpen && (
            <button onClick={() => setSidebar(true)}
              aria-label="Open sidebar"
              className="mr-3 text-lg hover:text-purple-400 transition"
              style={{ color: 'var(--muted)' }}>
              <span aria-hidden="true">☰</span>
            </button>
          )}
          <Link href="/" aria-label={t('app.home')} className="mr-3 text-lg hover:text-purple-400 transition" style={{ color: 'var(--muted)' }} title={t('app.home')}>
            <span aria-hidden="true">⌂</span>
          </Link>
          <h1 className="text-base font-bold mr-5" style={{ color: 'var(--text)' }}>
            🌍 {t('app.title')}
          </h1>
          {(['dashboard', 'chat'] as const).map(tb => (
            <button key={tb} onClick={() => setTab(tb)}
              className={`px-4 py-2 text-sm font-semibold border-b-2 transition mr-1 ${
                tab === tb ? 'border-purple-500' : 'border-transparent'
              }`}
              style={{ color: tab === tb ? 'var(--text)' : 'var(--muted)' }}>
              {tb === 'dashboard' ? `📊 ${t('app.dashboard')}` : `💬 ${t('app.chat')}`}
            </button>
          ))}

          <div className="flex-1" />

          <button onClick={handleShare}
            aria-label={t('app.share')}
            className="ml-2 px-3 py-1.5 text-xs font-semibold rounded-md border transition hover:border-purple-500 flex items-center gap-1.5"
            style={{ color: copied ? 'var(--accent)' : 'var(--text)', borderColor: 'var(--border)' }}
            title={t('app.share')}>
            <span aria-hidden="true">{copied ? '✓' : '🔗'}</span>
            <span>{copied ? t('app.linkCopied') : t('app.share')}</span>
          </button>
          <Link href="/settings"
            aria-label={t('app.settings')}
            className="ml-2 text-lg hover:text-purple-400 transition"
            style={{ color: 'var(--muted)' }}
            title={t('app.settings')}>
            <span aria-hidden="true">⚙️</span>
          </Link>
          <Link href="/admin"
            aria-label={t('app.admin')}
            className="ml-2 text-lg hover:text-purple-400 transition"
            style={{ color: 'var(--muted)' }}
            title={t('app.admin')}>
            <span aria-hidden="true">🛠️</span>
          </Link>
          <button onClick={toggleLang}
            aria-label="Switch language (English / Arabic)"
            className="ml-2 px-3 py-1.5 text-xs font-semibold rounded-md border transition hover:border-purple-500"
            style={{ color: 'var(--text)', borderColor: 'var(--border)' }}
            title="EN / AR">
            {lang === 'en' ? 'العربية' : 'English'}
          </button>
          <button onClick={toggleTheme}
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            className="ml-2 px-3 py-1.5 text-xs font-semibold rounded-md border transition hover:border-purple-500"
            style={{ color: 'var(--text)', borderColor: 'var(--border)' }}
            title="Toggle theme">
            <span aria-hidden="true">{theme === 'dark' ? '☀️' : '🌙'}</span>
          </button>
        </header>

        <main className="flex-1 overflow-y-auto">
          {tab === 'dashboard'
            ? <Dashboard
                selectedDumps={selected}
                allTimelines={timelines}
                activeTimeline={activeTimeline}
                onTimelineSelect={handleTimelineSelect}
                allCountries={allCountries}
                allCountryCounts={allCountryCounts}
                activeCountry={activeCountry}
                onCountrySelect={handleCountrySelect}
                filters={filters}
                onFilterChange={handleFilterChange}
              />
            : <Chat selectedDumps={selected} model={model} filters={filters} />
          }
        </main>
      </div>
    </div>
  );
}
