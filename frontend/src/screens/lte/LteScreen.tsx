import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams } from 'react-router'
import { apiFetch } from '../../api/client'
import { reconnectText, useLiveSocket } from '../../api/useLiveSocket'
import type { LteMessage, LteSample, LteState, RouterDetail } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { RouterSections } from '../../shell/RouterSections'
import { ActionsCard } from './ActionsCard'
import { AtConsole } from './AtConsole'
import { ModemCard } from './ModemCard'
import { SettingsCard } from './SettingsCard'
import { SignalCharts } from './SignalCharts'
import { EMPTY_SERIES, pushLte, type LteSeries } from './signal'
import { SignalTiles, StatusCard } from './StatusCard'

/** The live signal: one sample every 10 s from /ws/lte while the screen is open; it reconnects (v1.0c D7). */
function useLiveSignal(routerId: string, enabled: boolean) {
  const [series, setSeries] = useState<LteSeries>(EMPTY_SERIES)
  const [sample, setSample] = useState<LteSample | null>(null)
  const [idle, setIdle] = useState<string | null>(null)
  const live = useLiveSocket<LteMessage>(enabled ? `/ws/lte/${routerId}` : null, undefined, (msg) => {
    if (msg.type === 'lte') {
      setIdle(null)
      setSample(msg.sample)
      setSeries((s) => pushLte(s, msg.sample))
    } else {
      setIdle(msg.reason)
    }
  })
  return { series, sample, idle: reconnectText(live) ?? idle }
}

export function LteScreen() {
  const { id = '' } = useParams()
  const detail = useQuery({ queryKey: ['router', id], queryFn: () => apiFetch<RouterDetail>(`/api/routers/${id}`) })
  const lte = useQuery({ queryKey: ['lte', id], queryFn: () => apiFetch<LteState>(`/api/routers/${id}/lte`) })
  const state = lte.data
  const live = useLiveSignal(id, state?.available === true)
  const name = detail.data?.record.name ?? id
  const nowMs = live.sample ? live.sample.t * 1000 : 0
  const client = useQueryClient()
  const refresh = (): void => {
    for (const key of ['lte', 'lte-options', 'network']) void client.invalidateQueries({ queryKey: [key, id] })
  }

  return (
    <main className="wrap">
      <div>
        <div className="eyebrow">
          <span className="mono">{detail.data?.record.host ?? ''}</span>
          {state?.device ? ` · ${state.device}` : ''}
        </div>
        <div className="hrow">
          <h1>LTE</h1>
          <Help topic={HELP.lte} />
        </div>
      </div>
      <RouterSections routerId={id} name={name} current="lte" />
      {lte.isPending && <div className="muted">Reading the modem…</div>}
      {lte.error && <div className="note x">{lte.error.message}</div>}
      {state && !state.available && <div className="note">{state.note}</div>}
      {state?.available && (
        <>
          {state.missing.length > 0 && <div className="note w">No answer from the modem for: {state.missing.join(', ')}</div>}
          {live.idle && (
            <div className="note w" role="status">
              {live.idle}
            </div>
          )}
          <div className="rf-cols">
            <StatusCard state={state} sample={live.sample} />
            <ModemCard routerId={id} modem={state.modem} opmode={state.opmode} />
          </div>
          <SignalTiles state={state} sample={live.sample} />
          <SignalCharts series={live.series} nowMs={nowMs} />
          <div className="rf-cols">
            <ActionsCard routerId={id} routerName={name} onDone={refresh} />
            <AtConsole routerId={id} />
          </div>
          <SettingsCard routerId={id} routerName={name} autoconnectNote={state.autoconnect_note} onApplied={refresh} />
        </>
      )}
    </main>
  )
}
