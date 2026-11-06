import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router'
import { ApiError, apiFetch } from '../../api/client'
import type { PortsState, RouterDetail } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { RouterSections } from '../../shell/RouterSections'
import { shortName } from '../net/rows'
import { FrontPanel } from './FrontPanel'
import { MirrorCard } from './MirrorCard'
import { VlanMatrix } from './VlanMatrix'

/** Ports, VLANs, mirroring (spec 7.5): the switch's sockets, VLAN membership and port mirror. */
export function PortsScreen() {
  const { id = '' } = useParams()
  const client = useQueryClient()
  const detail = useQuery({ queryKey: ['router', id], queryFn: () => apiFetch<RouterDetail>(`/api/routers/${id}`) })
  const ports = useQuery({ queryKey: ['ports', id], queryFn: () => apiFetch<PortsState>(`/api/routers/${id}/ports`) })
  const name = detail.data?.record.name ?? id
  const refresh = (): void => {
    void client.invalidateQueries({ queryKey: ['ports', id] })
    void client.invalidateQueries({ queryKey: ['network', id] })
    void client.invalidateQueries({ queryKey: ['router', id] })
  }
  const cards = { routerId: id, short: shortName(name, id), onApplied: refresh }
  const state = ports.data
  return (
    <main className="wrap">
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <div>
          <div className="eyebrow">
            <span className="mono">{detail.data?.record.host ?? ''}</span>
            {detail.data?.summary ? ` · ${detail.data.summary.model}` : ''}
            {state?.switch ? ` · ${state.switch}` : ''}
          </div>
          <div className="hrow">
            <h1>Ports, VLANs, mirroring</h1>
            <Help topic={HELP.ports} />
          </div>
        </div>
      </div>
      <RouterSections routerId={id} name={name} current="ports" />
      {ports.isError && <div className="note x">{ports.error instanceof ApiError ? ports.error.detail : String(ports.error)}</div>}
      {state && !state.managed && (
        <div className="note w">This router&apos;s switch is not managed by swconfig, so the app shows no ports for it. Its network devices are on LuCI&apos;s Network pages.</div>
      )}
      {state?.managed && (
        <>
          <FrontPanel {...cards} state={state} />
          <VlanMatrix {...cards} state={state} />
          <MirrorCard {...cards} state={state} />
        </>
      )}
    </main>
  )
}
