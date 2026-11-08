import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams } from 'react-router'
import { ApiError, apiFetch } from '../../api/client'
import type { DiscoveryState, RouterDetail } from '../../api/types'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import { RouterSections } from '../../shell/RouterSections'
import { ConfigSection } from './ConfigSection'
import { CustomSection } from './CustomSection'
import { ImageSection } from './ImageSection'
import { OverlaySection } from './OverlaySection'

/** Discovery (spec 7.8): how this router differs from its image, its custom tools, copies and flashing. */
export function DiscoveryScreen() {
  const { id = '' } = useParams()
  const client = useQueryClient()
  const detail = useQuery({ queryKey: ['router', id], queryFn: () => apiFetch<RouterDetail>(`/api/routers/${id}`) })
  const discovery = useQuery({
    queryKey: ['discovery', id],
    queryFn: () => apiFetch<DiscoveryState>(`/api/routers/${id}/discovery`),
  })
  const [isFlashing, setFlashing] = useState(false)
  const name = detail.data?.record.name ?? id
  const state = discovery.data
  return (
    <main className="wrap">
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <div>
          <div className="eyebrow">
            <span className="mono">{detail.data?.record.host ?? ''}</span>
            {state ? ` · ${state.board} ${state.revision}` : ''}
          </div>
          <div className="hrow">
            <h1>Discovery</h1>
            <Help topic={HELP.discovery} />
          </div>
        </div>
        <span className="spacer" />
        <HelpTip topic={HELP.discovery}>
          <button
            className="btn"
            type="button"
            disabled={discovery.isFetching}
            onClick={() => void client.invalidateQueries({ queryKey: ['discovery', id] })}
          >
            {discovery.isFetching ? 'Reading…' : 'Refresh'}
          </button>
        </HelpTip>
      </div>
      <RouterSections routerId={id} name={name} current="discovery" />
      {discovery.isError && (
        <div className="note x">{discovery.error instanceof ApiError ? discovery.error.detail : String(discovery.error)}</div>
      )}
      {state && <ImageSection routerId={id} state={state} onFlash={() => setFlashing(true)} />}
      {state?.profile && <OverlaySection routerId={id} state={state} />}
      {state?.profile && <ConfigSection state={state} />}
      {state?.profile && <CustomSection routerId={id} state={state} />}
      {isFlashing && <div className="muted">Flashing comes with the flash dialog.</div>}
    </main>
  )
}
