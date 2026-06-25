'use client';

import { DumpInfo } from '@/lib/types';
import { ModelOption } from '@/lib/api';

const COUNTRY_FLAGS: Record<string, string> = {
  Qatar: '🇶🇦', UAE: '🇦🇪', 'Saudi Arabia': '🇸🇦',
  Bahrain: '🇧🇭', Kuwait: '🇰🇼', Oman: '🇴🇲',
};

const SOURCE_ICONS: Record<string, string> = {
  Bayt: '📌',
  LinkedIn: '💼',
};

interface Props {
  dumps: DumpInfo[];
  timelines: string[];
  selected: string[];
  model: string;
  models: ModelOption[];
  isOpen: boolean;
  onToggle: (id: string) => void;
  onSelectAll: () => void;
  onClearAll: () => void;
  onModelChange: (m: string) => void;
  onCollapse: () => void;
}

export default function Sidebar({
  dumps, timelines, selected, model, models, isOpen,
  onToggle, onSelectAll, onClearAll, onModelChange, onCollapse,
}: Props) {
  // Group by source → country
  const bySource: Record<string, Record<string, DumpInfo[]>> = {};
  for (const d of dumps) {
    const src = d._source ?? 'Bayt';
    if (!bySource[src]) bySource[src] = {};
    if (!bySource[src][d._country]) bySource[src][d._country] = [];
    bySource[src][d._country].push(d);
  }

  const totalJobs = dumps
    .filter(d => selected.includes(d._dump_id))
    .reduce((s, d) => s + d.count, 0);

  // Collapsed state — show only a thin strip with toggle
  if (!isOpen) {
    return (
      <aside
        className="flex flex-col items-center pt-4 gap-3 border-r"
        style={{ width: 44, background: 'var(--bg-alt)', borderColor: 'var(--border)', flexShrink: 0 }}>
        <button
          onClick={onCollapse}
          title="Open sidebar"
          className="text-lg hover:text-purple-400 transition"
          style={{ color: 'var(--muted)' }}>
          ☰
        </button>
        <div className="text-xs font-semibold mt-2" style={{ color: 'var(--accent)', writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}>
          {selected.length} datasets
        </div>
      </aside>
    );
  }

  return (
    <aside
      className="flex flex-col gap-4 p-4 overflow-y-auto border-r"
      style={{ width: 256, minWidth: 256, background: 'var(--bg-alt)', borderColor: 'var(--border)' }}>

      {/* Header + collapse button */}
      <div className="flex items-start justify-between">
        <div>
          <div className="text-base font-bold" style={{ color: 'var(--text)' }}>🌍 GCC Job Market</div>
          <div className="text-xs" style={{ color: 'var(--muted)' }}>Intelligence Assistant</div>
        </div>
        <button
          onClick={onCollapse}
          title="Collapse sidebar"
          className="text-lg mt-0.5 hover:text-purple-400 transition"
          style={{ color: 'var(--muted)' }}>
          ✕
        </button>
      </div>

      <hr style={{ borderColor: 'var(--border)' }} />

      {/* Dataset selector */}
      <div>
        <div className="text-xs font-bold mb-2 uppercase tracking-wide" style={{ color: 'var(--text)' }}>
          📂 Datasets
        </div>
        <div className="flex gap-2 mb-3">
          <button onClick={onSelectAll}
            className="flex-1 text-xs py-1 rounded border hover:bg-purple-500/10 hover:border-purple-500 transition"
            style={{ borderColor: 'var(--border)', color: 'var(--muted)' }}>
            All
          </button>
          <button onClick={onClearAll}
            className="flex-1 text-xs py-1 rounded border hover:bg-white/5 transition"
            style={{ borderColor: 'var(--border)', color: 'var(--muted)' }}>
            None
          </button>
        </div>

        {Object.entries(bySource).sort().map(([source, byCountry]) => (
          <div key={source} className="mb-4">
            <div className="text-xs font-bold mb-2 uppercase tracking-wide" style={{ color: 'var(--text)' }}>
              {SOURCE_ICONS[source] ?? '📂'} {source}
            </div>
            {Object.entries(byCountry).sort().map(([country, cDumps]) => (
              <div key={country} className="mb-2 pl-2">
                <div className="text-xs font-semibold mb-1" style={{ color: 'var(--muted)' }}>
                  {COUNTRY_FLAGS[country] ?? '🌍'} {country}
                </div>
                {cDumps.sort((a, b) => a._timeline.localeCompare(b._timeline)).map(d => (
                  <label key={d._dump_id} className="flex items-start gap-2 mb-1.5 cursor-pointer group">
                    <input
                      type="checkbox"
                      checked={selected.includes(d._dump_id)}
                      onChange={() => onToggle(d._dump_id)}
                      className="accent-purple-500 mt-0.5"
                    />
                    <span className="text-xs leading-tight" style={{ color: 'var(--muted)' }}>
                      <span className="group-hover:text-purple-400 transition" style={{ color: 'var(--text)' }}>
                        {d._timeline}
                      </span>
                      <br />
                      {d.count.toLocaleString()} jobs
                    </span>
                  </label>
                ))}
              </div>
            ))}
          </div>
        ))}

        <div className="text-xs font-bold mt-2" style={{ color: 'var(--accent)' }}>
          📊 {totalJobs > 0 ? `${totalJobs.toLocaleString()} jobs selected` : 'None selected'}
        </div>
      </div>

      <hr style={{ borderColor: 'var(--border)' }} />

      {/* Model selector */}
      <div>
        <div className="text-xs font-bold mb-2 uppercase tracking-wide" style={{ color: 'var(--text)' }}>
          🤖 Model
        </div>
        {models.length === 0 && (
          <div className="text-xs" style={{ color: 'var(--muted)' }}>Loading models…</div>
        )}
        {models.map(({ label, value }) => (
          <label key={value} className="flex items-start gap-2 mb-2 cursor-pointer">
            <input
              type="radio"
              name="model"
              value={value}
              checked={model === value}
              onChange={() => onModelChange(value)}
              className="accent-purple-500 mt-0.5"
            />
            <span className="text-xs leading-tight" style={{ color: model === value ? 'var(--text)' : 'var(--muted)' }}>
              {label}
            </span>
          </label>
        ))}
      </div>

      <hr style={{ borderColor: 'var(--border)' }} />

      <div className="text-xs mt-auto pb-2" style={{ color: 'var(--muted)' }}>
        Sources: Bayt.com · LinkedIn<br />
        {timelines.join(' · ')}
      </div>
    </aside>
  );
}
