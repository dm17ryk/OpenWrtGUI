import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams } from 'react-router'
import { ApiError, apiFetch } from '../../api/client'
import type { NetworkState, RouterDetail } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { RouterSections } from '../../shell/RouterSections'
import { DhcpCard } from './DhcpCard'
import { DnsCard } from './DnsCard'
import { FixedHosts, type HostRow } from './FixedHosts'
import { Interfaces } from './Interfaces'
import { Leases } from './Leases'
import { RoutesCard } from './RoutesCard'

/** Network and DHCP (spec 7.4): router addresses, DHCP, fixed addresses, Wi-Fi access, leases, DNS, routes. */
export function NetworkScreen() {
  const { id = '' } = useParams()
  const client = useQueryClient()
  const detail = useQuery({ queryKey: ['router', id], queryFn: () => apiFetch<RouterDetail>(`/api/routers/${id}`) })
  const net = useQuery({ queryKey: ['network', id], queryFn: () => apiFetch<NetworkState>(`/api/routers/${id}/network`) })
  // New fixed-address rows live here so Active leases' "Make fixed" can add one to the Fixed addresses card.
  const [newHosts, setNewHosts] = useState<HostRow[]>([])
  const name = detail.data?.record.name ?? id
  const host = detail.data?.record.host ?? ''
  const refresh = (): void => {
    void client.invalidateQueries({ queryKey: ['network', id] })
    void client.invalidateQueries({ queryKey: ['router', id] })
    void client.invalidateQueries({ queryKey: ['routers'] })
    void client.invalidateQueries({ queryKey: ['net-leases', id] })
    void client.invalidateQueries({ queryKey: ['net-routes-live', id] })
  }
  const cards = { routerId: id, routerName: name, onApplied: refresh }
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
      {net.data && (
        <>
          <Interfaces {...cards} host={host} state={net.data} />
          <DhcpCard {...cards} state={net.data} />
          <FixedHosts {...cards} state={net.data} added={newHosts} onAdded={setNewHosts} />
          <Leases routerId={id} state={net.data} onMakeFixed={(row) => setNewHosts([...newHosts, row])} />
          <DnsCard {...cards} state={net.data} />
          <RoutesCard {...cards} state={net.data} />
        </>
      )}
    </main>
  )
}
