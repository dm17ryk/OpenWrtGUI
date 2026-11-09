import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch } from '../../api/client'
import type { LogEntry } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'

type Kind = 'system' | 'kernel'
const LENGTHS = [100, 500, 2000] as const
const FOLLOW_MS = 5000
// most severe first; logread says warn / error, dmesg warning / err
const SEVERITY = ['emerg', 'alert', 'crit', 'err', 'warning', 'notice', 'info', 'debug'] as const
const ALIAS: Record<string, string> = { warn: 'warning', error: 'err', panic: 'emerg' }

function rank(level: string | null | undefined): number {
  if (!level) return SEVERITY.length
  const at = SEVERITY.indexOf((ALIAS[level] ?? level) as (typeof SEVERITY)[number])
  return at < 0 ? SEVERITY.length : at
}

function line(e: LogEntry): string {
  const when = e.time ?? (e.seconds != null ? `[${e.seconds.toFixed(2)}]` : '')
  const who = e.source ? `${e.source}${e.pid != null ? `[${e.pid}]` : ''}: ` : ''
  return [when, e.level ?? '', `${who}${e.message}`].filter(Boolean).join(' ')
}

/** The system log or the kernel log, filtered in the browser; Follow reads it again every 5 s. */
export function LogsTab({ routerId }: { routerId: string }) {
  const [kind, setKind] = useState<Kind>('system')
  const [lines, setLines] = useState<(typeof LENGTHS)[number]>(100)
  const [text, setText] = useState('')
  const [level, setLevel] = useState('')
  const [follow, setFollow] = useState(false)
  const logs = useQuery({
    queryKey: ['system-logs', routerId, kind, lines],
    queryFn: () => apiFetch<LogEntry[]>(`/api/routers/${routerId}/system/logs?kind=${kind}&lines=${lines}`),
    refetchInterval: follow ? FOLLOW_MS : false,
  })
  const needle = text.trim().toLowerCase()
  const shown = (logs.data ?? []).filter(
    (e) => (!needle || line(e).toLowerCase().includes(needle)) && (!level || rank(e.level) <= rank(level)),
  )
  const label = kind === 'system' ? 'System log' : 'Kernel log'
  return (
    <section className="card stack" aria-labelledby="system-logs-h">
      <div className="row">
        <div className="hrow">
          <h2 id="system-logs-h">Logs</h2>
          <Help topic={HELP.systemLogs} />
        </div>
        <div className="spacer" />
        <div className="seg" role="group" aria-label="Log">
          {(['system', 'kernel'] as const).map((k) => (
            <button key={k} type="button" className={kind === k ? 'on' : ''} aria-pressed={kind === k} onClick={() => setKind(k)}>
              {k === 'system' ? 'System' : 'Kernel'}
            </button>
          ))}
        </div>
      </div>
      <div className="row">
        <label className="field">
          <span>Lines</span>
          <select value={lines} onChange={(e) => setLines(Number(e.target.value) as (typeof LENGTHS)[number])}>
            {LENGTHS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Level</span>
          <select value={level} onChange={(e) => setLevel(e.target.value)}>
            <option value="">all</option>
            {SEVERITY.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="field" style={{ flex: 1 }}>
          <span>Filter</span>
          <input className="in" value={text} onChange={(e) => setText(e.target.value)} placeholder="text in the line" />
        </label>
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
          <span>Follow</span>
        </label>
      </div>
      {logs.error && <div className="note x">{logs.error instanceof ApiError ? logs.error.detail : logs.error.message}</div>}
      {logs.isPending && <div className="muted">Reading the log…</div>}
      {logs.data && (
        <ul className="code stack" role="log" aria-label={label} style={{ gap: 2, listStyle: 'none', margin: 0 }}>
          {shown.map((e, i) => (
            // a log has no key of its own: the same line can repeat
            // eslint-disable-next-line react/no-array-index-key
            <li key={i} className="mono">
              {line(e)}
            </li>
          ))}
        </ul>
      )}
      {logs.data && <div className="muted">{`${shown.length} of ${logs.data.length} lines`}</div>}
    </section>
  )
}
