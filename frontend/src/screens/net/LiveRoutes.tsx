import { useQuery } from '@tanstack/react-query'
import { ApiError, apiFetch } from '../../api/client'
import type { LiveTables } from '../../api/types'

type Props = { routerId: string; family: 4 | 6 }

/** What the kernel routes now (`ip -j route show table all`, `ip -j rule`); raw text on images without `ip -j`. */
export function LiveRoutes({ routerId, family }: Props) {
  const live = useQuery({
    queryKey: ['net-routes-live', routerId],
    queryFn: () => apiFetch<LiveTables>(`/api/routers/${routerId}/network/routes/live`),
  })
  const routes = (live.data?.routes ?? []).filter((r) => r.family === family)
  const rules = (live.data?.rules ?? []).filter((r) => r.family === family)
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row">
        <div className="eyebrow">Live routing table</div>
        <div className="spacer" />
        <button className="btn" type="button" disabled={live.isFetching} onClick={() => void live.refetch()}>
          {live.isFetching ? 'Reading…' : 'Refresh'}
        </button>
      </div>
      {live.isError && <div className="note x">{live.error instanceof ApiError ? live.error.detail : String(live.error)}</div>}
      {live.data?.raw ? (
        <pre className="code">{live.data.raw}</pre>
      ) : (
        <div className="scroll-x">
          <table className="tbl" aria-label="Live routing table">
            <thead>
              <tr>
                <th>Destination</th>
                <th>Gateway</th>
                <th>Device</th>
                <th>Metric</th>
                <th>Protocol</th>
                <th>Table</th>
              </tr>
            </thead>
            <tbody>
              {routes.map((r) => (
                <tr key={`${r.table}-${r.type}-${r.dst}-${r.dev}-${r.gateway}-${r.metric}`}>
                  <td className="mono">{r.type === 'unicast' ? r.dst : `${r.type} ${r.dst}`}</td>
                  <td className="mono">{r.gateway ?? '—'}</td>
                  <td className="mono">{r.dev ?? '—'}</td>
                  <td>{r.metric ?? '—'}</td>
                  <td>{r.proto ?? '—'}</td>
                  <td>{r.table}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rules.length > 0 && (
            <table className="tbl" aria-label="Live rules">
              <thead>
                <tr>
                  <th>Priority</th>
                  <th>From</th>
                  <th>Lookup</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={`${r.priority}-${r.src}-${r.lookup}`}>
                    <td>{r.priority}</td>
                    <td className="mono">{r.src ?? 'all'}</td>
                    <td>{r.lookup ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
