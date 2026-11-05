import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router'
import { ApiError, apiFetch } from '../../api/client'
import type { NetworkState, RouterDetail } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { RouterSections } from '../../shell/RouterSections'
import { Interfaces } from './Interfaces'

/** Network and DHCP (spec 7.4): router addresses, DHCP, fixed addresses, Wi-Fi access, leases, DNS, routes. */
export function NetworkScreen() {
  const { id = '' } = useParams()
  const client = useQueryClient()
  const detail = useQuery({ queryKey: ['router', id], queryFn: () => apiFetch<RouterDetail>(`/api/routers/${id}`) })
  const net = useQuery({ queryKey: ['network', id], queryFn: () => apiFetch<NetworkState>(`/api/routers/${id}/network`) })
  const name = detail.data?.record.name ?? id
  const host = detail.data?.record.host ?? ''
  const refresh = (): void => {
    void client.invalidateQueries({ queryKey: ['network', id] })
    void client.invalidateQueries({ queryKey: ['router', id] })
    void client.invalidateQueries({ queryKey: ['routers'] })
  }
  return (
    <main className="wrap">
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <div>
          <div className="eyebrow">
            <span className="mono">{host}</span>
            {detail.data?.summary ? ` · ${detail.data.summary.model}` : ''}
          </div>
          <div className="hrow">
            <h1>Network and DHCP</h1>
            <Help topic={HELP.network} />
          </div>
        </div>
      </div>
      <RouterSections routerId={id} name={name} current="network" />
      {net.isError && <div className="note x">{net.error instanceof ApiError ? net.error.detail : String(net.error)}</div>}
      {net.data && <Interfaces routerId={id} routerName={name} host={host} state={net.data} onApplied={refresh} />}
    </main>
  )
}
