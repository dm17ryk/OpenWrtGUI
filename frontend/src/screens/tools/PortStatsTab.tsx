import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch } from '../../api/client'
import type { PortCounters, PortStats } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { type Column, formatBits, formatBytes, rate, sinceBaseline } from './portRates'

const POLL_MS = 5000

type Reads = { base: PortStats | null; prev: PortStats | null; last: PortStats | null }

function clock(readAt: number): string {
  return new Date(readAt * 1000).toLocaleTimeString('en-GB', { hour12: false })
}

function linkText(p: PortCounters): string {
  if (!p.link) return 'down'
  return p.speed_mbps === null ? 'up' : `${p.speed_mbps} Mbit/s`
}

function since(reads: Reads, num: number, column: Column): number | 'reset' | null {
  return reads.base && reads.last ? sinceBaseline(reads.base, reads.last, num, column) : null
}

function countText(v: number | 'reset' | null, bytes = false): string {
  if (v === null) return '—'
  if (v === 'reset') return 'reset'
  return bytes ? formatBytes(v) : String(v)
}

function rateText(reads: Reads, num: number, column: Column, isStale: boolean): string {
  if (isStale || !reads.prev || !reads.last) return '—'
  const r = rate(reads.prev, reads.last, num, column)
  if (r === null) return '—'
  return r === 'reset' ? 'reset' : formatBits(r * 8)
}

function ErrorsCell({ value }: { value: number | 'reset' | null }) {
  return <td className={typeof value === 'number' && value > 0 ? 'warn' : undefined}>{countText(value)}</td>
}

/**
 * Port statistics (spec 7.8 Phase 2, v1.2a R5-R7): each switch port's counters, read every 5 s while the tab is
 * open, counted from the tab's own start; the router's counters are never cleared.
 */
export function PortStatsTab({ routerId }: { routerId: string }) {
  const query = useQuery({
    queryKey: ['port-stats', routerId],
    queryFn: () => apiFetch<PortStats>(`/api/routers/${routerId}/ports/stats`),
    refetchInterval: POLL_MS,
    refetchIntervalInBackground: false,
  })
  const [reads, setReads] = useState<Reads>({ base: null, prev: null, last: null })
  const data = query.data
  if (data && reads.last !== data) {
    // a new read: keep the one before it for the rates (React's "adjust state while rendering" pattern)
    setReads({ base: reads.base ?? data, prev: reads.last, last: data })
  }
  const last = reads.last
  const isStale = query.isError
  return (
    <section className="card stack" aria-labelledby="port-stats-h">
      <div className="hrow">
        <h2 id="port-stats-h">Port statistics</h2>
        <Help topic={HELP.toolsPortStats} />
        <span className="spacer" />
        {reads.base && last && !last.note && (
          <>
            <span className="muted">Since {clock(reads.base.read_at)}</span>
            <button className="btn" type="button" onClick={() => setReads((r) => ({ ...r, base: r.last }))}>
              Start over
            </button>
          </>
        )}
      </div>
      {query.isPending && <div className="muted">Reading the switch…</div>}
      {query.error && (
        <div className="note x">{query.error instanceof ApiError ? query.error.detail : query.error.message}</div>
      )}
      {last?.note && <div className="note">{last.note}</div>}
      {last && !last.note && (
        <div style={{ overflowX: 'auto' }}>
          <table>
            <thead>
              <tr>
                <th>Port</th>
                <th>Link</th>
                <th>Rx packets</th>
                <th>Rx bytes</th>
                <th>Rx errors</th>
                <th>Tx packets</th>
                <th>Tx bytes</th>
                <th>Tx errors</th>
                <th>Rx rate</th>
                <th>Tx rate</th>
              </tr>
            </thead>
            <tbody>
              {last.ports.map((p) => (
                <PortRows key={p.num} port={p} reads={reads} isStale={isStale} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function PortRows({ port, reads, isStale }: { port: PortCounters; reads: Reads; isStale: boolean }) {
  const raw = Object.entries(port.raw)
  return (
    <>
      <tr>
        <td>{port.label}</td>
        <td>{linkText(port)}</td>
        <td>{countText(since(reads, port.num, 'rx_packets'))}</td>
        <td>{countText(since(reads, port.num, 'rx_bytes'), true)}</td>
        <ErrorsCell value={since(reads, port.num, 'rx_errors')} />
        <td>{countText(since(reads, port.num, 'tx_packets'))}</td>
        <td>{countText(since(reads, port.num, 'tx_bytes'), true)}</td>
        <ErrorsCell value={since(reads, port.num, 'tx_errors')} />
        <td>{rateText(reads, port.num, 'rx_bytes', isStale)}</td>
        <td>{rateText(reads, port.num, 'tx_bytes', isStale)}</td>
      </tr>
      <tr className="sub">
        <td colSpan={10}>
          {raw.length === 0 ? (
            <span className="muted">No counters</span>
          ) : (
            <details>
              <summary>All counters</summary>
              <dl className="kv mono">
                {raw.map(([name, v]) => (
                  <div key={name}>
                    <dt>{name}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
            </details>
          )}
        </td>
      </tr>
    </>
  )
}
