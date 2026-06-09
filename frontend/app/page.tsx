'use client';

import { useEffect, useState } from 'react';
import { fetchDatasets, fetchModels, ModelOption } from '@/lib/api';
import { DumpInfo } from '@/lib/types';
import Sidebar from '@/components/Sidebar';
import Dashboard from '@/components/Dashboard';
import Chat from '@/components/Chat';

export default function Home() {
  const [dumps,     setDumps]     = useState<DumpInfo[]>([]);
  const [timelines, setTimelines] = useState<string[]>([]);
  const [selected,  setSelected]  = useState<string[]>([]);
  const [models,    setModels]    = useState<ModelOption[]>([]);
  const [model,     setModel]     = useState('');
  const [tab,       setTab]       = useState<'dashboard' | 'chat'>('dashboard');
  const [sidebarOpen, setSidebar] = useState(true);
  const [loading,   setLoading]   = useState(true);

  useEffect(() => {
    Promise.all([fetchDatasets(), fetchModels()])
      .then(([datasets, modelData]) => {
        setDumps(datasets.dumps);
        setTimelines(datasets.timelines);
        setSelected(datasets.dumps.map(d => d._dump_id));
        setModels(modelData.models);
        setModel(modelData.default);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

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
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-purple-400 animate-pulse">Loading GCC Job Market Intelligence…</div>
      </div>
    );
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
        onModelChange={setModel}
        onCollapse={() => setSidebar(o => !o)}
      />

      <div className="flex-1 flex flex-col overflow-hidden">

        {/* Top bar */}
        <header className="flex items-center gap-0 px-4 pt-3 pb-0 border-b shrink-0"
                style={{ borderColor: '#30363d' }}>
          {!sidebarOpen && (
            <button onClick={() => setSidebar(true)}
              className="mr-3 text-lg hover:text-purple-400 transition"
              style={{ color: '#8b98a5' }}>
              ☰
            </button>
          )}
          <h1 className="text-base font-bold text-white mr-5">
            🌍 GCC Job Market Intelligence
          </h1>
          {(['dashboard', 'chat'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-2 text-sm font-semibold border-b-2 transition mr-1 ${
                tab === t ? 'border-purple-500 text-white' : 'border-transparent'
              }`}
              style={{ color: tab === t ? 'white' : '#8b98a5' }}>
              {t === 'dashboard' ? '📊 Dashboard' : '💬 Chat'}
            </button>
          ))}
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
              />
            : <Chat selectedDumps={selected} model={model} />
          }
        </main>
      </div>
    </div>
  );
}
