import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch } from '../../api/client'
import type { PortCounters, PortStats } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { type Column, type Since, accumulate, emptySince, formatBits, formatBytes, rate } from './portRates'

const POLL_MS = 5000

/** The baseline's time, the last two reads (for the rates), and the counts added up since the baseline. */
type Reads = { base: PortStats | null; prev: PortStats | null; last: PortStats | null; since: Since }

const NONE: Reads = { base: null, prev: null, last: null, since: {} }

function clock(readAt: number): string {
  return new Date(readAt * 1000).toLocaleTimeString('en-GB', { hour12: false })
}

function linkText(p: PortCounters): string {
  if (!p.link) return 'down'
  return p.speed_mbps === null ? 'up' : `${p.speed_mbps} Mbit/s`
}

function since(reads: Reads, num: number, column: Column): number | null {
  return reads.since[num]?.[column] ?? null
}

function countText(v: number | null, bytes = false): string {
  if (v === null) return '—'
  return bytes ? formatBytes(v) : String(v)
}

function rateText(reads: Reads, num: number, column: Column, isStale: boolean): string {
  if (isStale || !reads.prev || !reads.last) return '—'
  const r = rate(reads.prev, reads.last, num, column)
  if (r === null) return '—'
  return r === 'reset' ? 'reset' : formatBits(r * 8)
}

function ErrorsCell({ value }: { value: number | null }) {
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
  const [reads, setReads] = useState<Reads>(NONE)
  // coming back to the tab starts from a fresh read, never the cached one of the last visit (final review M2)
  const data = query.isFetchedAfterMount ? query.data : undefined
  if (data && reads.last !== data) {
    // a new read (React's "adjust state while rendering" pattern): the first is the baseline; each later one
    // adds its step to the counts, so any number of wraps add up
    setReads(
      reads.last === null
        ? { base: data, prev: null, last: data, since: emptySince(data) }
        : { base: reads.base, prev: reads.last, last: data, since: accumulate(reads.since, reads.last, data) },
    )
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
            <button
              className="btn"
              type="button"
              onClick={() => setReads((r) => (r.last ? { ...r, base: r.last, since: emptySince(r.last) } : r))}
            >
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
        <div className="scroll-x">
          <table className="tbl">
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
