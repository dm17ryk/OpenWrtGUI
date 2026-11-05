import { useQuery } from '@tanstack/react-query'
import { ApiError, apiFetch } from '../../api/client'
import type { Lease, NetworkState } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import type { HostRow } from './FixedHosts'
import { expiresIn } from './rows'

const REFRESH_MS = 10_000

type Props = { routerId: string; state: NetworkState; onMakeFixed: (row: HostRow) => void }

/** Who has an address from the router right now (IPv4 and IPv6); Make fixed turns one into a fixed address. */
export function Leases({ routerId, state, onMakeFixed }: Props) {
  const leases = useQuery({
    queryKey: ['net-leases', routerId],
    queryFn: () => apiFetch<Lease[]>(`/api/routers/${routerId}/network/leases`),
    refetchInterval: REFRESH_MS,
  })
  const fixed = new Set(state.hosts.flatMap((h) => h.macs))
  const rows = leases.data ?? []
  return (
    <section className="card stack" aria-labelledby="leases-h">
      <div className="row">
        <div className="hrow">
          <h2 id="leases-h">Active leases</h2>
          <Help topic={HELP.netLeases} />
        </div>
        <span className="muted">refreshed every 10 s</span>
      </div>
      {leases.isError && <div className="note x">{leases.error instanceof ApiError ? leases.error.detail : String(leases.error)}</div>}
      <div className="scroll-x">
        <table className="tbl" aria-label="Active leases">
          <thead>
            <tr>
              <th>Host</th>
              <th>MAC</th>
              <th>IP</th>
              <th>Expires in</th>
              <th>
                <span className="sr-only">Make fixed</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((l) => (
              <tr key={`${l.family}-${l.ip}`}>
                <td>{l.hostname ?? '—'}</td>
                <td className="mono">{l.mac ?? '—'}</td>
                <td className="mono">{l.ip}</td>
                <td>{expiresIn(l.expires_s)}</td>
                <td>
                  {l.family === 4 && l.mac && fixed.has(l.mac) && <span className="b neu">fixed</span>}
                  {l.family === 4 && l.mac && !fixed.has(l.mac) && (
                    <button
                      className="btn"
                      type="button"
                      aria-label={`Make ${l.ip} fixed`}
                      onClick={() => onMakeFixed({ section: null, name: l.hostname ?? '', mac: l.mac ?? '', ip: l.ip, leasetime: '', gets_address: true })}
                    >
                      Make fixed
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {leases.isSuccess && rows.length === 0 && <div className="muted">No leases: nothing has an address from this router.</div>}
    </section>
  )
}
