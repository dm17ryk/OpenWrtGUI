import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { ApiError, apiFetch } from '../../api/client'
import type { AccessState, SsidAccess } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'

function summary(s: SsidAccess): string {
  if (s.policy === 'everyone') return 'Everyone'
  const n = s.maclist.length
  return `${s.policy === 'deny' ? 'Block listed' : 'Only listed'} · ${n} ${n === 1 ? 'device' : 'devices'}`
}

/** Who may join each SSID, in one line each; the lists are changed on Network & DHCP. */
export function WhoMayJoin({ routerId }: { routerId: string }) {
  const access = useQuery({
    queryKey: ['net-access', routerId],
    queryFn: () => apiFetch<AccessState>(`/api/routers/${routerId}/network/access`),
  })
  return (
    <section className="card stack" aria-labelledby="who-h">
      <div className="hrow">
        <h2 id="who-h">Who may join</h2>
        <Help topic={HELP.wifiWho} />
      </div>
      {access.isError && <div className="note x">{access.error instanceof ApiError ? access.error.detail : String(access.error)}</div>}
      {(access.data?.ssids ?? []).map((s) => (
        <div className="row" key={s.section}>
          <span>{s.ssid}</span>
          <span className="muted mono">{s.radio}</span>
          <span className={s.policy === 'everyone' ? 'b neu' : 'b har'}>{summary(s)}</span>
        </div>
      ))}
      <Link to={`/routers/${routerId}/network#wifi-access`}>Change on Network &amp; DHCP › Wi-Fi access by MAC</Link>
    </section>
  )
}
