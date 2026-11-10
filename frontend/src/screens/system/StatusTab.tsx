import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { ApiError, apiFetch, openSocket } from '../../api/client'
import type { Connections, SystemMessage, SystemOverview, SystemSample } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { uptimeText } from '../net/rows'
import { LiveCharts } from './LiveCharts'
import { EMPTY_SYSTEM, mib, pushSystem, type SystemSeries } from './live'

/** One sample every 3 s from /ws/system while the Status tab is open. */
function useLiveSystem(routerId: string) {
  const [series, setSeries] = useState<SystemSeries>(EMPTY_SYSTEM)
  const [sample, setSample] = useState<SystemSample | null>(null)
  const [idle, setIdle] = useState<string | null>(null)
  useEffect(() => {
    const ws = openSocket(`/ws/system/${routerId}`)
    ws.onmessage = (ev: MessageEvent<string>) => {
      const msg = JSON.parse(ev.data) as SystemMessage
      if (msg.type === 'system') {
        setIdle(null)
        setSample(msg.sample)
        setSeries((s) => pushSystem(s, msg.sample))
      } else {
        setIdle(msg.reason)
      }
    }
    ws.onclose = () => setIdle('Lost the connection to OpenWrtGUI. Open the System screen again.')
    return () => {
      ws.onclose = null
      ws.close()
    }
  }, [routerId])
  return { series, sample, idle }
}

function space(total: number | null | undefined, free: number | null | undefined): string {
  return total != null && free != null ? `${mib(free * 1024)} free of ${mib(total * 1024)}` : '—'
}

function OverviewCard({ o, routerId }: { o: SystemOverview; routerId: string }) {
  const rows: ReadonlyArray<readonly [string, string]> = [
    ['Model', o.model ?? '—'],
    ['Board', o.board_name ?? '—'],
    ['Firmware', o.release ?? '—'],
    ['Kernel', o.kernel ?? '—'],
    ['Host name', o.hostname ?? '—'],
    ['Local time', o.localtime != null ? new Date(o.localtime * 1000).toISOString().replace('T', ' ').slice(0, 19) : '—'],
    ['Uptime', o.uptime_s != null ? uptimeText(o.uptime_s) : '—'],
    ['Load (1 / 5 / 15 min)', o.load ? o.load.map((v) => v.toFixed(2)).join(' / ') : '—'],
    ['Memory', o.memory_total != null && o.memory_available != null ? `${mib(o.memory_available)} free of ${mib(o.memory_total)}` : '—'],
    ['Root file system', space(o.root_total_kib, o.root_free_kib)],
    ['Temporary files', space(o.tmp_total_kib, o.tmp_free_kib)],
  ]
  return (
    <section className="card stack" aria-labelledby="system-overview-h">
      <div className="hrow">
        <h2 id="system-overview-h">Overview</h2>
        <Help topic={HELP.systemOverview} />
      </div>
      <dl className="kv">
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: 'contents' }}>
            <dt>{k}</dt>
            <dd className="mono">{v}</dd>
          </div>
        ))}
      </dl>
      <div className="row">
        <Link className="btn" to={`/routers/${routerId}/network`}>
          Live routes
        </Link>
        <Link className="btn" to={`/routers/${routerId}/rf`}>
          RF live
        </Link>
      </div>
    </section>
  )
}

function ConnectionsCard({ routerId }: { routerId: string }) {
  const [open, setOpen] = useState(false)
  const conns = useQuery({
    queryKey: ['system-connections', routerId],
    queryFn: () => apiFetch<Connections>(`/api/routers/${routerId}/system/connections`),
    enabled: open,
  })
  return (
    <section className="card stack" aria-labelledby="system-conns-h">
      <div className="row">
        <div className="hrow">
          <h2 id="system-conns-h">Connections</h2>
          <Help topic={HELP.systemConnections} />
        </div>
        <div className="spacer" />
        <button type="button" className="btn" onClick={() => (open ? void conns.refetch() : setOpen(true))}>
          {open ? 'Read again' : 'Show connections'}
        </button>
      </div>
      {conns.error && <div className="note x">{conns.error instanceof ApiError ? conns.error.detail : String(conns.error)}</div>}
      {conns.data?.note && <div className="note">{conns.data.note}</div>}
      {conns.data && !conns.data.note && (
        <div className="scroll-x">
          <table className="tbl" aria-label="Connections">
            <thead>
              <tr>
                <th>Protocol</th>
                <th>Source</th>
                <th>Destination</th>
                <th>State</th>
                <th>Bytes</th>
              </tr>
            </thead>
            <tbody>
              {conns.data.rows.map((c, i) => (
                // the table has no key of its own: the same pair can show twice in different states
                // eslint-disable-next-line react/no-array-index-key
                <tr key={i}>
                  <td>{c.proto}</td>
                  <td className="mono">{c.src ? `${c.src}${c.sport != null ? `:${c.sport}` : ''}` : '—'}</td>
                  <td className="mono">{c.dst ? `${c.dst}${c.dport != null ? `:${c.dport}` : ''}` : '—'}</td>
                  <td>{c.state ?? '—'}</td>
                  <td className="mono">{c.bytes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

type Props = { routerId: string; overview: SystemOverview }

/** The overview, the live charts and the connection table on request. */
export function StatusTab({ routerId, overview }: Props) {
  const live = useLiveSystem(routerId)
  const nowMs = live.sample ? live.sample.t * 1000 : 0
  return (
    <>
      {overview.missing.length > 0 && <div className="note w">No answer from the router for: {overview.missing.join(', ')}</div>}
      {live.idle && (
        <div className="note w" role="status">
          {live.idle}
        </div>
      )}
      <OverviewCard o={overview} routerId={routerId} />
      <LiveCharts series={live.series} nowMs={nowMs} />
      <ConnectionsCard routerId={routerId} />
    </>
  )
}
