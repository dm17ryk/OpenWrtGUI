import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useParams } from 'react-router'
import { ApiError, apiFetch } from '../../api/client'
import type { ClearIn, FaultsState, RouterDetail } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import { RouterSections } from '../../shell/RouterSections'
import { NetChange } from '../net/NetChange'
import { shortName } from '../net/rows'
import { ArmedList } from './ArmedList'
import { CaptureCard } from './CaptureCard'
import { FaultCards } from './FaultCards'
import { EMPTY_DRAFT, type FaultDraft, faultRequest } from './faults'
import { TargetPicker } from './TargetPicker'

/** A clock for "clears in 42 s" that ticks only while a held fault is armed. */
function useNow(ticking: boolean): Date {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    if (!ticking) return undefined
    const timer = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(timer)
  }, [ticking])
  return now
}

/** Faults and capture (spec 7.7): arm a fault on one target, see and clear what is armed, capture traffic. */
export function FaultsScreen() {
  const { id = '' } = useParams()
  const client = useQueryClient()
  const detail = useQuery({ queryKey: ['router', id], queryFn: () => apiFetch<RouterDetail>(`/api/routers/${id}`) })
  const faults = useQuery({ queryKey: ['faults', id], queryFn: () => apiFetch<FaultsState>(`/api/routers/${id}/faults`) })
  const [draft, setDraft] = useState<FaultDraft>(EMPTY_DRAFT)
  // undefined: not clearing; null: everything; a list: those faults
  const [clearing, setClearing] = useState<string[] | null | undefined>(undefined)
  const name = detail.data?.record.name ?? id
  const short = shortName(name, id)
  const state = faults.data
  const armed = state?.armed ?? []
  const now = useNow(armed.some((f) => f.until !== null))
  // a router without prio or ets can impair only what comes from the target
  const fault = state?.caps.band === null && draft.netem.direction !== 'from' ? { ...draft, netem: { ...draft.netem, direction: 'from' as const } } : draft
  const refresh = (): void => {
    void client.invalidateQueries({ queryKey: ['faults', id] })
    void client.invalidateQueries({ queryKey: ['routers'] })
    void client.invalidateQueries({ queryKey: ['firewall', id] })
  }
  const arm = usePlanApply(`/api/routers/${id}/faults`, faultRequest(fault), () => {
    setDraft({ ...fault, kind: null })
    refresh()
  })
  const clearBody: ClearIn | null = clearing === undefined ? null : { ids: clearing }
  const clear = usePlanApply(`/api/routers/${id}/faults/clear`, clearBody, () => {
    setClearing(undefined)
    refresh()
  })
  const startClear = (ids: string[] | null): void => {
    clear.clear()
    setClearing(ids)
  }
  return (
    <main className="wrap">
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <div>
          <div className="eyebrow">
            <span className="mono">{detail.data?.record.host ?? ''}</span>
            {detail.data?.summary ? ` · ${detail.data.summary.model}` : ''}
          </div>
          <div className="hrow">
            <h1>Faults and capture</h1>
            <Help topic={HELP.faults} />
          </div>
        </div>
        <span className="spacer" />
        {state && <span className={armed.length ? 'b park' : 'b air'}>{armed.length ? `${armed.length} armed` : 'nothing armed'}</span>}
        <HelpTip topic={HELP.faultClear}>
          <button className="btn" type="button" disabled={armed.length === 0} onClick={() => startClear(null)}>
            Clear everything
          </button>
        </HelpTip>
      </div>
      <RouterSections routerId={id} name={name} current="faults" />
      {faults.isError && <div className="note x">{faults.error instanceof ApiError ? faults.error.detail : String(faults.error)}</div>}
      <ArmedList armed={armed} now={now} onClear={startClear} />
      {(clearing !== undefined || clear.result) && (
        <div className="card stack" role="group" aria-label="Clear faults">
          <NetChange change={clear} short={short} helpTopic={HELP.faultClear} show={clearBody !== null} applyLabel="Clear" provenText="Cleared" />
        </div>
      )}
      {state && (
        <>
          <TargetPicker state={state} short={short} target={draft.target} onPick={(target) => setDraft({ ...fault, target })} />
          <FaultCards state={state} draft={fault} onChange={setDraft} />
          <section className="card stack" aria-labelledby="fault-run-h">
            <h2 id="fault-run-h">Will run on {short}</h2>
            {faultRequest(fault) === null && !arm.result && <div className="muted">Pick a target and a fault above; the exact commands show here before anything runs.</div>}
            <NetChange change={arm} short={short} helpTopic={HELP.faults} show={faultRequest(fault) !== null} applyLabel="Arm" provenText="Armed and proven" />
          </section>
        </>
      )}
      <CaptureCard routerId={id} />
    </main>
  )
}
