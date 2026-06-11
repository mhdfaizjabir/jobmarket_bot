'use client';

import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { createSession, clearSession, streamChat } from '@/lib/api';
import { Message, RetrievalInfo } from '@/lib/types';

function friendlyError(err: unknown): string {
  if (!(err instanceof Error)) return 'Something went wrong. Please try again.';
  if (err.name === 'AbortError') return '';
  if (err.message.includes('429')) return 'Too many requests — please wait a moment before asking again.';
  if (err.message.includes('401') || err.message.includes('403')) return 'Authentication error. Please refresh the page.';
  if (err.message.includes('500')) return 'Server error. Please try again in a moment.';
  if (err.message.includes('Failed to fetch') || err.message.includes('NetworkError')) return 'Could not reach the server. Check your connection.';
  return `Error: ${err.message}`;
}

// ── Retrieval Panel ─────────────────────────────────────────────────────────

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = score > 0.7 ? '#00c9a7' : score > 0.5 ? '#ffd93d' : '#ff6b6b';
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-1.5 rounded-full overflow-hidden" style={{ background: '#30363d' }}>
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="text-xs font-mono" style={{ color }}>{score.toFixed(2)} / 1.00</span>
    </div>
  );
}

function RetrievalPanel({ info }: { info: RetrievalInfo }) {
  const [open, setOpen] = useState(false);
  const dc = info.decomposed ?? {};
  const filters = dc.filters ?? {};
  const hitCount = info.semantic_hits?.length ?? 0;

  return (
    <div className="mb-3 rounded-lg overflow-hidden border text-xs" style={{ borderColor: '#30363d' }}>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-white/5 transition"
        style={{ background: '#0f1117', color: '#8b98a5' }}>
        <span>
          🔍 <span className="font-semibold">Retrieval process</span>
          <span className="ml-2 text-purple-400">{info.layers_used?.join(' · ')}</span>
          {hitCount > 0 && <span className="ml-2 text-teal-400">{hitCount} semantic hits</span>}
        </span>
        <span>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="p-3 space-y-3" style={{ background: '#0d1117', borderTop: '1px solid #30363d' }}>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="font-semibold mb-1.5" style={{ color: '#c9d1d9' }}>Query decomposition</div>
              <div className="space-y-1" style={{ color: '#8b98a5' }}>
                <div>
                  Aggregation needed:
                  <span className={`ml-1 font-semibold ${info.needs_agg ? 'text-yellow-400' : 'text-green-400'}`}>
                    {info.needs_agg ? 'Yes' : 'No'}
                  </span>
                </div>
                {Object.keys(filters).length > 0 && (
                  <div>Filters: <span className="text-purple-400">{JSON.stringify(filters)}</span></div>
                )}
                {dc.analysis_types?.length > 0 && (
                  <div>Analysis: <span className="text-blue-400">{dc.analysis_types.join(', ')}</span></div>
                )}
                {dc.resolved_question && dc.resolved_question !== dc.semantic_query && (
                  <div className="mt-1 italic" style={{ color: '#6b7280' }}>
                    Resolved: {dc.resolved_question.slice(0, 120)}
                  </div>
                )}
              </div>
            </div>
            <div>
              <div className="font-semibold mb-1.5" style={{ color: '#c9d1d9' }}>Layers used</div>
              <div className="space-y-1">
                {(info.layers_used ?? []).map(l => (
                  <div key={l} className="flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-purple-400 shrink-0" />
                    <span style={{ color: '#8b98a5' }}>{l}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {info.semantic_hits?.length > 0 && (
            <div>
              <div className="font-semibold mb-1.5" style={{ color: '#c9d1d9' }}>
                Top {info.semantic_hits.length} semantic matches
              </div>
              <div className="space-y-1.5">
                {info.semantic_hits.map((h, i) => (
                  <div key={i} className="flex items-center gap-3 py-1 border-b" style={{ borderColor: '#1f2937' }}>
                    <ScoreBar score={h.score} />
                    <div className="flex-1 min-w-0">
                      <span className="font-semibold truncate block" style={{ color: '#c9d1d9' }}>{h.title}</span>
                      <span style={{ color: '#6b7280' }}>{h.company} · {h.country} · {h.timeline}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {info.sql_snippet && (
            <div>
              <div className="font-semibold mb-1" style={{ color: '#c9d1d9' }}>SQL / Pandas result (preview)</div>
              <pre className="overflow-x-auto p-2 rounded text-xs leading-relaxed"
                   style={{ background: '#161b22', color: '#8b98a5', border: '1px solid #30363d' }}>
                {info.sql_snippet}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Markdown renderer — safe, no dangerouslySetInnerHTML ─────────────────────

function BotMessage({ content, streaming }: { content: string; streaming?: boolean }) {
  return (
    <div className="text-sm leading-relaxed" style={{ color: '#e4e6f0' }}>
      <ReactMarkdown
        components={{
          p:    ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
          ul:   ({ children }) => <ul className="list-disc list-inside mb-2 space-y-0.5">{children}</ul>,
          ol:   ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-0.5">{children}</ol>,
          li:   ({ children }) => <li style={{ color: '#c9d1d9' }}>{children}</li>,
          strong: ({ children }) => <strong style={{ color: '#ffffff' }}>{children}</strong>,
          em:   ({ children }) => <em style={{ color: '#a5b4fc' }}>{children}</em>,
          code: ({ children, className }) => {
            const isBlock = className?.includes('language-');
            return isBlock
              ? <pre className="overflow-x-auto p-3 rounded my-2 text-xs" style={{ background: '#0d1117', border: '1px solid #30363d', color: '#8b98a5' }}><code>{children}</code></pre>
              : <code className="px-1 py-0.5 rounded text-xs" style={{ background: '#21262d', color: '#f97316' }}>{children}</code>;
          },
          h1: ({ children }) => <h1 className="text-base font-bold mb-2 mt-3" style={{ color: '#ffffff' }}>{children}</h1>,
          h2: ({ children }) => <h2 className="text-sm font-bold mb-1.5 mt-3" style={{ color: '#e4e6f0' }}>{children}</h2>,
          h3: ({ children }) => <h3 className="text-xs font-bold mb-1 mt-2" style={{ color: '#c9d1d9' }}>{children}</h3>,
          blockquote: ({ children }) => <blockquote className="border-l-2 pl-3 my-2 italic" style={{ borderColor: '#6c63ff', color: '#8b98a5' }}>{children}</blockquote>,
          table: ({ children }) => <div className="overflow-x-auto my-2"><table className="text-xs w-full border-collapse" style={{ borderColor: '#30363d' }}>{children}</table></div>,
          th: ({ children }) => <th className="px-2 py-1 text-left font-semibold border" style={{ borderColor: '#30363d', background: '#21262d', color: '#c9d1d9' }}>{children}</th>,
          td: ({ children }) => <td className="px-2 py-1 border" style={{ borderColor: '#30363d', color: '#8b98a5' }}>{children}</td>,
        }}
      >
        {content}
      </ReactMarkdown>
      {streaming && (
        <span className="inline-block w-2 h-4 ml-1 bg-purple-400 animate-pulse rounded-sm align-middle" />
      )}
    </div>
  );
}

// ── Main Chat ────────────────────────────────────────────────────────────────

interface MessageWithId extends Message {
  id: string;
}

interface Props {
  selectedDumps: string[];
  model: string;
}

export default function Chat({ selectedDumps, model }: Props) {
  const [sessionId,    setSessionId]    = useState<string>('');
  const [sessionError, setSessionError] = useState<string>('');
  const [messages,     setMessages]     = useState<MessageWithId[]>([]);
  const [input,        setInput]        = useState('');
  const [streaming,    setStreaming]     = useState(false);
  const [searching,    setSearching]    = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef  = useRef<AbortController | null>(null);
  const inputRef  = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let cancelled = false;
    createSession()
      .then(id => { if (!cancelled) setSessionId(id); })
      .catch(() => {
        if (!cancelled) setSessionError('Could not connect to server. Please refresh the page.');
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, searching]);

  function makeId() {
    return `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  }

  function stopStreaming() {
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
    setSearching(false);
    setMessages(prev => {
      const copy = [...prev];
      if (copy.length && copy[copy.length - 1].streaming) {
        copy[copy.length - 1] = { ...copy[copy.length - 1], streaming: false };
      }
      return copy;
    });
  }

  async function send(question: string) {
    if (!question.trim()) return;
    if (!sessionId) {
      setSessionError('Not connected to server. Please refresh the page.');
      return;
    }
    if (streaming) stopStreaming();

    setInput('');
    setTimeout(() => inputRef.current?.focus(), 0);

    const userMsg: MessageWithId  = { id: makeId(), role: 'user', content: question };
    const asstMsg: MessageWithId  = { id: makeId(), role: 'assistant', content: '', streaming: true };
    setMessages(prev => [...prev, userMsg, asstMsg]);
    setStreaming(true);
    setSearching(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      for await (const event of streamChat(question, sessionId, model, selectedDumps, controller.signal)) {
        if (event.type === 'retrieval') {
          setSearching(false);
          setMessages(prev => {
            const copy = [...prev];
            copy[copy.length - 1] = { ...copy[copy.length - 1], retrieval: event.info };
            return copy;
          });
        } else if (event.type === 'token') {
          setSearching(false);
          setMessages(prev => {
            const copy = [...prev];
            copy[copy.length - 1] = {
              ...copy[copy.length - 1],
              content: copy[copy.length - 1].content + event.token,
            };
            return copy;
          });
        }
      }
    } catch (e: unknown) {
      setSearching(false);
      const msg = friendlyError(e);
      if (msg) {
        setMessages(prev => {
          const copy = [...prev];
          copy[copy.length - 1] = { ...copy[copy.length - 1], content: msg, streaming: false };
          return copy;
        });
      }
    } finally {
      abortRef.current = null;
      setSearching(false);
      setMessages(prev => {
        const copy = [...prev];
        if (copy.length && copy[copy.length - 1].streaming) {
          copy[copy.length - 1] = { ...copy[copy.length - 1], streaming: false };
        }
        return copy;
      });
      setStreaming(false);
    }
  }

  async function handleClear() {
    if (streaming) stopStreaming();
    if (sessionId) await clearSession(sessionId);
    setMessages([]);
  }

  if (sessionError) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center space-y-3">
          <div className="text-red-400 text-sm">{sessionError}</div>
          <button
            onClick={() => { setSessionError(''); createSession().then(setSessionId).catch(() => setSessionError('Still cannot connect. Check if the server is running.')); }}
            className="text-xs px-4 py-2 rounded-lg border hover:border-purple-500 transition"
            style={{ borderColor: '#30363d', color: '#8b98a5' }}>
            Retry connection
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col" style={{ height: 'calc(100vh - 57px)' }}>

      {/* Header */}
      <div className="flex items-center justify-between px-6 py-2 border-b" style={{ borderColor: '#30363d' }}>
        <span className="text-xs" style={{ color: '#8b98a5' }}>
          {selectedDumps.length ? `${selectedDumps.length} datasets selected` : 'All data'} ·
          model: <code className="text-purple-400 ml-1">{model.split('/').pop()}</code>
          {!sessionId && <span className="ml-2 text-yellow-400">connecting…</span>}
        </span>
        {messages.length > 0 && (
          <button onClick={handleClear}
            className="text-xs px-3 py-1 rounded border hover:border-red-500 hover:text-red-400 transition"
            style={{ borderColor: '#30363d', color: '#8b98a5' }}>
            Clear chat
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="space-y-4">
            <div className="text-center mt-8">
              <div className="text-3xl mb-2">🌍</div>
              <div className="font-bold text-white text-lg">GCC Job Market Assistant</div>
              <div className="text-sm mt-1" style={{ color: '#8b98a5' }}>
                Ask anything about the GCC job market
              </div>
            </div>
          </div>
        )}

        {messages.map(m => (
          <div key={m.id}>
            {m.role === 'assistant' && m.retrieval && m.retrieval.layers_used.length > 0 && (
              <RetrievalPanel info={m.retrieval} />
            )}

            <div className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[80%] rounded-xl px-4 py-3 text-sm leading-relaxed ${m.role === 'user' ? 'bg-purple-600 text-white' : ''}`}
                style={m.role === 'assistant' ? { background: '#161b22', border: '1px solid #30363d' } : {}}>
                {m.role === 'assistant'
                  ? <BotMessage content={m.content} streaming={m.streaming} />
                  : m.content
                }
              </div>
            </div>
          </div>
        ))}

        {/* Searching indicator — shown between user message and first token */}
        {searching && (
          <div className="flex justify-start">
            <div className="rounded-xl px-4 py-3 text-xs flex items-center gap-2"
                 style={{ background: '#161b22', border: '1px solid #30363d', color: '#8b98a5' }}>
              <div className="w-3 h-3 rounded-full border border-purple-400 border-t-transparent animate-spin" />
              Searching database…
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-6 py-4 border-t" style={{ borderColor: '#30363d' }}>
        <form onSubmit={e => { e.preventDefault(); send(input); }} className="flex gap-3 items-end">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input); } }}
            placeholder={streaming ? 'Type your next question — press Enter to interrupt…' : 'Ask about the GCC job market…'}
            rows={2}
            disabled={!!sessionError}
            className="flex-1 resize-none rounded-xl px-4 py-3 text-sm outline-none border focus:border-purple-500 transition disabled:opacity-40"
            style={{ background: '#161b22', borderColor: '#30363d', color: '#e4e6f0' }}
          />
          {streaming ? (
            <button type="button" onClick={stopStreaming}
              className="px-5 py-3 rounded-xl font-semibold text-sm transition"
              style={{ background: '#374151', color: '#e4e6f0', border: '1px solid #4b5563' }}>
              ⏹ Stop
            </button>
          ) : (
            <button type="submit" disabled={!input.trim() || !sessionId}
              className="px-5 py-3 rounded-xl font-semibold text-sm transition disabled:opacity-40"
              style={{ background: '#6c63ff', color: 'white' }}>
              ➤
            </button>
          )}
        </form>
        <div className="text-xs mt-2" style={{ color: '#4a5568' }}>
          {streaming
            ? 'Enter to interrupt and ask a new question · ⏹ Stop to cancel'
            : 'Shift+Enter for new line · Enter to send'}
        </div>
      </div>
    </div>
  );
}
