'use client';

import { useEffect, useState } from 'react';
import { fetchDashboard } from '@/lib/api';
import { DashboardData } from '@/lib/types';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts';

// ── Design tokens ────────────────────────────────────────────────────────────
const TL_PALETTE = ['#6c63ff', '#00c9a7', '#ffd93d', '#ff6b6b', '#a855f7'];
const CAT_PALETTE = ['#6c63ff','#00c9a7','#ffd93d','#ff6b6b','#a855f7','#4ecdc4','#ff8e53','#44b09e','#667eea','#f093fb','#4facfe','#43e97b'];

const TT_STYLE = {
  backgroundColor: 'var(--card-alt)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  color: 'var(--text)',
  fontSize: 12,
  padding: '8px 12px',
};
const TT_LABEL  = { color: 'var(--text)', fontWeight: 600, marginBottom: 4 };
const TT_ITEM   = { color: 'var(--muted)', padding: '2px 0' };
const AX_STYLE  = { fill: 'var(--muted)', fontSize: 11 };
const Y_STYLE   = { fill: 'var(--text)', fontSize: 11 };

const FLAGS: Record<string, string> = {
  All: '🌍', Qatar: '🇶🇦', UAE: '🇦🇪', 'Saudi Arabia': '🇸🇦',
  Bahrain: '🇧🇭', Kuwait: '🇰🇼', Oman: '🇴🇲',
};

// ── Shared chart helpers ──────────────────────────────────────────────────────

function tt(extra?: object) {
  return (
    <Tooltip
      contentStyle={TT_STYLE}
      labelStyle={TT_LABEL}
      itemStyle={TT_ITEM}
      formatter={(v, n) => [Number(v).toLocaleString(), String(n)]}
      {...extra}
    />
  );
}

/** Single-series horizontal bar (sorted descending = top item largest) */
function HBar({ data, x, y, color = '#6c63ff', height }: {
  data: Record<string, unknown>[]; x: string; y: string; color?: string; height: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={[...data].reverse()} layout="vertical"
        margin={{ left: 8, right: 60, top: 4, bottom: 4 }}>
        <XAxis type="number" tick={AX_STYLE} axisLine={false} tickLine={false}
          tickFormatter={(v) => Number(v) >= 1000 ? `${(Number(v)/1000).toFixed(1)}k` : String(v)} />
        <YAxis type="category" dataKey={y} width={175}
          tick={Y_STYLE} axisLine={false} tickLine={false} />
        {tt()}
        <Bar dataKey={x} fill={color} radius={[0, 4, 4, 0]}
          label={{ position: 'right', fill: 'var(--muted)', fontSize: 10,
            formatter: (v: unknown) => Number(v) >= 1000 ? `${(Number(v)/1000).toFixed(1)}k` : String(v) }} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Stacked horizontal bar — one segment per timeline */
function HBarStacked({ rows, timelines, tlColors, height }: {
  rows: Record<string, unknown>[]; timelines: string[]; tlColors: Record<string, string>; height: number;
}) {
  const sorted = [...rows].sort((a, b) => {
    const ta = timelines.reduce((s, t) => s + ((a[t] as number) ?? 0), 0);
    const tb = timelines.reduce((s, t) => s + ((b[t] as number) ?? 0), 0);
    return ta - tb; // asc = top is largest in horizontal chart
  });

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={sorted} layout="vertical"
        margin={{ left: 8, right: 60, top: 4, bottom: 4 }}>
        <XAxis type="number" tick={AX_STYLE} axisLine={false} tickLine={false}
          tickFormatter={(v) => Number(v) >= 1000 ? `${(Number(v)/1000).toFixed(1)}k` : String(v)} />
        <YAxis type="category" dataKey="sector" width={175}
          tick={Y_STYLE} axisLine={false} tickLine={false} />
        {tt()}
        <Legend wrapperStyle={{ fontSize: 11, color: 'var(--muted)', paddingTop: 8 }} />
        {timelines.map((tl, i) => (
          <Bar key={tl} dataKey={tl} stackId="s" fill={tlColors[tl] ?? TL_PALETTE[i % TL_PALETTE.length]}
            radius={i === timelines.length - 1 ? [0, 4, 4, 0] : [0, 0, 0, 0]} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Vertical bar */
function VBar({ data, x, y, height }: { data: Record<string,unknown>[]; x: string; y: string; height: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ left: 0, right: 8, top: 4, bottom: 75 }}>
        <XAxis dataKey={x}
          tick={{ fill: 'var(--muted)', fontSize: 10, angle: -40, textAnchor: 'end' }}
          axisLine={false} tickLine={false} interval={0} />
        <YAxis tick={AX_STYLE} axisLine={false} tickLine={false} />
        {tt()}
        <Bar dataKey={y} radius={[4, 4, 0, 0]}>
          {data.map((_, i) => <Cell key={i} fill={CAT_PALETTE[i % CAT_PALETTE.length]} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Donut */
function Donut({ data, name, value }: { data: Record<string,unknown>[]; name: string; value: string }) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <PieChart>
        <Pie data={data} dataKey={value} nameKey={name}
          cx="50%" cy="44%" outerRadius={88} innerRadius={36}
          label={({ name: n, percent }) => (percent ?? 0) > 0.04 ? `${n} ${((percent ?? 0)*100).toFixed(0)}%` : ''}
          labelLine={false}>
          {data.map((_, i) => <Cell key={i} fill={CAT_PALETTE[i % CAT_PALETTE.length]} />)}
        </Pie>
        {tt()}
        <Legend wrapperStyle={{ fontSize: 11, color: 'var(--muted)' }} />
      </PieChart>
    </ResponsiveContainer>
  );
}

// ── Card wrapper ──────────────────────────────────────────────────────────────

function Card({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl mb-5 overflow-hidden"
         style={{ background: 'var(--card)', border: '1px solid var(--border)' }}>
      <div className="px-5 pt-4 pb-3 border-b" style={{ borderColor: 'var(--border)' }}>
        <div className="font-bold text-sm" style={{ color: 'var(--text)' }}>{title}</div>
        {subtitle && <div className="text-xs mt-0.5" style={{ color: 'var(--muted)' }}>{subtitle}</div>}
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

// ── Navigation components ─────────────────────────────────────────────────────

function CountryTabs({ countries, counts, active, onChange }: {
  countries: string[]; counts: Record<string, number>; active: string; onChange: (c: string) => void;
}) {
  const all = ['All', ...countries];
  return (
    <div className="flex gap-2 flex-wrap">
      {all.map(c => {
        const isActive = active === c;
        return (
          <button key={c} onClick={() => onChange(c)}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold transition-all"
            style={isActive
              ? { background: 'var(--accent)', color: '#fff', border: '1px solid var(--accent)' }
              : { background: 'var(--card)', color: 'var(--muted)', border: '1px solid var(--border)' }}>
            <span>{FLAGS[c] ?? '🌍'}</span>
            <span>{c}</span>
            {c !== 'All' && counts[c] !== undefined && (
              <span className="ml-1 px-1.5 py-0.5 rounded text-xs"
                style={{ background: isActive ? 'rgba(255,255,255,0.2)' : 'var(--card-alt)', color: isActive ? '#fff' : 'var(--muted)', fontSize: 10 }}>
                {counts[c].toLocaleString()}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

function TimelinePills({ timelines, tlColors, active, onChange }: {
  timelines: string[]; tlColors: Record<string, string>; active: string; onChange: (t: string) => void;
}) {
  const all = ['All', ...timelines];
  return (
    <div className="flex gap-2 flex-wrap items-center">
      <span className="text-xs font-semibold mr-1" style={{ color: 'var(--muted)' }}>Timeline:</span>
      {all.map((t, i) => {
        const isActive = active === t;
        const bgColor  = t === 'All' ? 'var(--accent)' : (tlColors[t] ?? TL_PALETTE[(i - 1) % TL_PALETTE.length]);
        return (
          <button key={t} onClick={() => onChange(t)}
            className="px-3 py-1 rounded-full text-xs font-semibold transition-all"
            style={isActive
              ? { background: bgColor, color: '#fff', border: `1px solid ${bgColor}` }
              : { background: 'transparent', color: 'var(--muted)', border: '1px solid var(--border)' }}>
            {t}
          </button>
        );
      })}
    </div>
  );
}

// ── Pivot helper ──────────────────────────────────────────────────────────────

function pivotSectors(raw: { sector: string; count: number; _timeline?: string }[]) {
  const timelines = [...new Set(raw.map(d => d._timeline).filter(Boolean))] as string[];
  if (!timelines.length) {
    return { rows: raw.map(d => ({ sector: d.sector, count: d.count })), timelines: [] };
  }
  const byKey: Record<string, Record<string, number>> = {};
  for (const d of raw) {
    if (!byKey[d.sector]) byKey[d.sector] = {};
    if (d._timeline) byKey[d.sector][d._timeline] = d.count;
  }
  const rows = Object.entries(byKey).map(([sector, vals]) => ({ sector, ...vals }));
  return { rows, timelines };
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  selectedDumps: string[];
  allTimelines: string[];
  activeTimeline: string;
  onTimelineSelect: (tl: string) => void;
  allCountries: string[];
  allCountryCounts: Record<string, number>;
  activeCountry: string;
  onCountrySelect: (c: string) => void;
}

export default function Dashboard({ selectedDumps, allTimelines, activeTimeline, onTimelineSelect, allCountries, allCountryCounts, activeCountry, onCountrySelect }: Props) {
  const [data,     setData]     = useState<DashboardData | null>(null);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState('');

  const [activeSector, setActiveSector] = useState('All');
  const [allSectors,     setAllSectors]     = useState<string[]>([]);

  // Fetch whenever dumps/country/timeline/sector change.
  // Sector is server-side so ALL charts (career level, skills, salary, etc.) reflect the selection.
  useEffect(() => {
    setLoading(true);
    fetchDashboard({
      dumps:  selectedDumps,
      sector: activeSector !== 'All' ? activeSector : undefined,
    })
      .then(d => {
        setData(d);
        setError('');
        // Only rebuild the sector pill list when no sector is active,
        // so the pills don't disappear after filtering.
        if (activeSector === 'All') {
          const secs = [...new Set(d.sectors.map(s => s.sector))].sort();
          setAllSectors(secs);
        }
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDumps, activeSector]);

  // Reset sector when selection, country, or timeline changes.
  useEffect(() => {
    setActiveSector('All');
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDumps, activeCountry, activeTimeline]);

  // Colors keyed on allTimelines so they stay consistent regardless of active filters
  const tlColors: Record<string, string> = {};
  allTimelines.forEach((t, i) => { tlColors[t] = TL_PALETTE[i % TL_PALETTE.length]; });

  // (country counts come from allCountryCounts prop — stable totals from dump metadata)

  const { rows: sectorRows, timelines: sectorTL } = pivotSectors(data?.sectors ?? []);
  const sectorHeight = Math.max(300, sectorRows.length * 36);

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 rounded-full border-2 border-purple-500 border-t-transparent animate-spin" />
        <div className="text-sm" style={{ color: 'var(--muted)' }}>Loading dashboard…</div>
      </div>
    </div>
  );

  if (error) return (
    <div className="p-8 text-center">
      <div className="text-red-400 text-sm">{error}</div>
    </div>
  );

  if (!data) return null;

  return (
    <div className="p-5 max-w-7xl mx-auto">

      {/* ── Navigation ─────────────────────────────────────────────────────── */}
      <div className="rounded-xl mb-5 p-4 space-y-3"
           style={{ background: 'var(--card)', border: '1px solid var(--border)' }}>
        <CountryTabs
          countries={allCountries}
          counts={allCountryCounts}
          active={activeCountry}
          onChange={onCountrySelect}
        />
        {allTimelines.length > 1 && (
          <TimelinePills
            timelines={allTimelines}
            tlColors={tlColors}
            active={activeTimeline}
            onChange={onTimelineSelect}
          />
        )}

        {/* Sector filter */}
        {allSectors.length > 0 && (
          <div className="flex items-center gap-3 flex-wrap pt-1 border-t" style={{ borderColor: 'var(--border)' }}>
            <span className="text-xs font-semibold" style={{ color: 'var(--muted)' }}>Sector:</span>
            <div className="flex gap-2 flex-wrap flex-1">
              <button
                onClick={() => setActiveSector('All')}
                className="px-3 py-1 rounded-full text-xs font-semibold transition-all"
                style={activeSector === 'All'
                  ? { background: 'var(--card-alt)', color: 'var(--text)', border: '1px solid var(--muted)' }
                  : { background: 'transparent', color: 'var(--muted)', border: '1px solid var(--border)' }}>
                All Sectors
              </button>
              {allSectors.map(s => (
                <button key={s} onClick={() => setActiveSector(s)}
                  className="px-3 py-1 rounded-full text-xs font-semibold transition-all"
                  style={activeSector === s
                    ? { background: 'var(--accent)', color: '#fff', border: '1px solid var(--accent)' }
                    : { background: 'transparent', color: 'var(--muted)', border: '1px solid var(--border)' }}>
                  {s}
                </button>
              ))}
            </div>
            {activeSector !== 'All' && (
              <button onClick={() => setActiveSector('All')}
                className="text-xs px-2 py-1 rounded hover:text-red-400 transition ml-auto"
                style={{ color: 'var(--muted)' }}>
                ✕ Clear
              </button>
            )}
          </div>
        )}
      </div>

      {/* ── KPI row ────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        {[
          {
            icon: '📋', label: 'Total Postings',
            value: data.total.toLocaleString(),
            sub: activeCountry !== 'All' ? `in ${activeCountry}` : `${allCountries.length} countries`,
          },
          {
            icon: '💰', label: 'Salary Coverage',
            value: `${data.salary.coverage_pct}%`,
            sub: data.salary.avg_usd ? `avg $${Number(data.salary.avg_usd).toLocaleString()}/mo` : 'of postings disclose',
          },
          data.kpi_mom
            ? {
                icon: '📈', label: `${data.kpi_mom.t1} → ${data.kpi_mom.t2}`,
                value: data.kpi_mom.c2.toLocaleString(),
                delta: `${data.kpi_mom.pct > 0 ? '+' : ''}${data.kpi_mom.pct}%`,
                sub: `from ${data.kpi_mom.c1.toLocaleString()}`,
              }
            : {
                icon: '🗓', label: 'Timeline',
                value: activeTimeline !== 'All' ? activeTimeline : 'All periods',
                sub: `${data.timelines.length} snapshots`,
              },
          activeSector !== 'All'
            ? { icon: '🏭', label: 'Sector Filter', value: activeSector, sub: `${data.total.toLocaleString()} postings` }
            : { icon: '🏢', label: 'Top Sector', value: sectorRows.length > 0 ? String(sectorRows[sectorRows.length - 1]?.sector ?? '—') : '—', sub: 'by posting volume' },
        ].map((k, i) => (
          <div key={i} className="rounded-xl p-4"
               style={{ background: 'var(--card)', border: '1px solid var(--border)' }}>
            <div className="text-xl mb-1">{k.icon}</div>
            <div className="text-xl font-bold leading-tight" style={{ color: 'var(--text)' }}>{k.value}</div>
            {'delta' in k && k.delta && (
              <div className={`text-xs font-bold mt-0.5 ${parseFloat(k.delta as string) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {k.delta}
              </div>
            )}
            <div className="text-xs mt-1 font-semibold" style={{ color: 'var(--muted)' }}>{k.label}</div>
            <div className="text-xs" style={{ color: 'var(--muted)' }}>{k.sub}</div>
          </div>
        ))}
      </div>

      {/* ── Sectors ────────────────────────────────────────────────────────── */}
      {sectorRows.length > 0 && (
        <Card
          title="📊 Postings by Sector"
          subtitle={sectorTL.length > 1 ? `Stacked by timeline — ${sectorTL.join(', ')}` : undefined}>
          {sectorTL.length > 1
            ? <HBarStacked rows={sectorRows} timelines={sectorTL} tlColors={tlColors} height={sectorHeight} />
            : <HBar data={sectorRows} x="count" y="sector" color="#6c63ff" height={sectorHeight} />
          }
        </Card>
      )}

      {/* ── Career level + Employment type ─────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {data.career_levels.length > 0 && (
          <Card title="🎯 Career Level" subtitle="Distribution across selected postings">
            <Donut data={data.career_levels} name="level" value="count" />
          </Card>
        )}
        {data.employment_types.length > 0 && (
          <Card title="💼 Employment Type">
            <Donut data={data.employment_types} name="type" value="count" />
          </Card>
        )}
      </div>

      {/* ── Salary ─────────────────────────────────────────────────────────── */}
      {data.salary.n_disclosed > 0 && (
        <Card
          title="💰 Salary Intelligence"
          subtitle={`${data.salary.coverage_pct}% of postings disclose salary — ${data.salary.n_disclosed.toLocaleString()} postings`}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {data.salary.by_sector.length > 0 && (
              <div>
                <div className="text-xs font-semibold mb-3" style={{ color: 'var(--muted)' }}>
                  Average Monthly Salary by Sector (USD)
                </div>
                <HBar
                  data={data.salary.by_sector}
                  x="avg_usd" y="sector" color="#00c9a7"
                  height={Math.max(260, data.salary.by_sector.length * 34)}
                />
              </div>
            )}
            {data.salary.distribution.length > 0 && (
              <div>
                <div className="text-xs font-semibold mb-3" style={{ color: 'var(--muted)' }}>
                  Salary Brackets (USD / month)
                </div>
                <VBar data={data.salary.distribution} x="bracket" y="count" height={300} />
              </div>
            )}
          </div>
        </Card>
      )}

      {/* ── Skills ─────────────────────────────────────────────────────────── */}
      {data.skills.length > 0 && (
        <Card title="🛠 Top In-Demand Skills" subtitle="Extracted from job postings across selected data">
          <HBar data={data.skills} x="count" y="skill" color="#a855f7"
            height={Math.max(280, data.skills.length * 30)} />
        </Card>
      )}

      {/* ── Job titles ─────────────────────────────────────────────────────── */}
      {data.job_titles.length > 0 && (
        <Card title="📋 Most Advertised Positions">
          <HBar data={data.job_titles} x="count" y="title" color="#ffd93d"
            height={Math.max(280, data.job_titles.length * 30)} />
        </Card>
      )}

      {/* ── Companies ──────────────────────────────────────────────────────── */}
      {data.companies.length > 0 && (
        <Card title="🏢 Top Hiring Companies">
          <HBar data={data.companies} x="count" y="company" color="#4ecdc4"
            height={Math.max(240, data.companies.length * 32)} />
        </Card>
      )}

      {/* ── Experience + Company size ───────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {data.experience.length > 0 && (
          <Card title="📅 Experience Required">
            <VBar data={data.experience} x="experience" y="count" height={280} />
          </Card>
        )}
        {data.company_size.length > 0 && (
          <Card title="🏭 Company Size">
            <Donut data={data.company_size} name="size" value="count" />
          </Card>
        )}
      </div>

      {/* ── Language + Location ────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {data.languages.length > 0 && (
          <Card title="🗣 Language Requirements">
            <VBar data={data.languages} x="language" y="count" height={260} />
          </Card>
        )}
        {data.locations.length > 0 && (
          <Card title="📍 Top Locations">
            <Donut data={data.locations} name="city" value="count" />
          </Card>
        )}
      </div>

      {/* ── Country comparison (only visible on "All" tab) ─────────────────── */}
      {activeCountry === 'All' && data.country_comparison.length > 1 && (
        <Card title="🌍 Volume by Country" subtitle="Share of total postings across selected datasets">
          <Donut data={data.country_comparison} name="country" value="count" />
        </Card>
      )}

      {/* ── Trends ─────────────────────────────────────────────────────────── */}
      {data.trends && (
        <Card
          title="📈 Market Trends"
          subtitle={`${data.trends.t1} → ${data.trends.t2} · ${data.trends.n1.toLocaleString()} → ${data.trends.n2.toLocaleString()} postings`}>
          <div className="flex items-center gap-3 mb-4">
            <span className={`text-2xl font-bold ${data.trends.overall_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {data.trends.overall_pct > 0 ? '+' : ''}{data.trends.overall_pct}%
            </span>
            <span className="text-sm" style={{ color: 'var(--muted)' }}>overall change</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <div className="text-xs font-bold text-green-400 mb-3 flex items-center gap-2">
                ▲ Growing Sectors
              </div>
              {data.trends.growing.length === 0
                ? <div className="text-xs" style={{ color: 'var(--muted)' }}>None in current selection</div>
                : data.trends.growing.map(r => (
                <div key={r.sector} className="flex items-center gap-3 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
                  <div className="flex-1">
                    <div className="text-xs font-semibold" style={{ color: 'var(--text)' }}>{r.sector}</div>
                    <div className="text-xs" style={{ color: 'var(--muted)' }}>
                      {r.count_t1.toLocaleString()} → {r.count_t2.toLocaleString()}
                    </div>
                  </div>
                  <span className="text-xs font-bold text-green-400 bg-green-400/10 px-2 py-0.5 rounded-full">
                    +{r.pct_change}%
                  </span>
                </div>
              ))}
            </div>
            <div>
              <div className="text-xs font-bold text-red-400 mb-3">▼ Declining Sectors</div>
              {data.trends.declining.length === 0
                ? <div className="text-xs" style={{ color: 'var(--muted)' }}>None in current selection</div>
                : data.trends.declining.map(r => (
                <div key={r.sector} className="flex items-center gap-3 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
                  <div className="flex-1">
                    <div className="text-xs font-semibold" style={{ color: 'var(--text)' }}>{r.sector}</div>
                    <div className="text-xs" style={{ color: 'var(--muted)' }}>
                      {r.count_t1.toLocaleString()} → {r.count_t2.toLocaleString()}
                    </div>
                  </div>
                  <span className="text-xs font-bold text-red-400 bg-red-400/10 px-2 py-0.5 rounded-full">
                    {r.pct_change}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}

    </div>
  );
}
