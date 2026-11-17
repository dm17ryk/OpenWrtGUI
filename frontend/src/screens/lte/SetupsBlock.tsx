import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { apiFetch, postJson } from '../../api/client'
import type { LteSetupSummary, NetApplyResult } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

const SAVE_WHEN = 'Save a good setup while LTE works'

function day(setup: LteSetupSummary): string {
  return setup.saved_at ? setup.saved_at.slice(0, 10) : 'an unknown day'
}

function label(setup: LteSetupSummary, routerId: string): string {
  if (!setup.readable) return `${setup.router_name} (cannot be read)`
  if (setup.router_id === routerId) return `This router's good setup, saved ${day(setup)}`
  return `${setup.router_name}, saved ${day(setup)} (not its SIM PIN)`
}

type Props = { routerId: string; works: boolean; onApplied: (result: NetApplyResult) => void }

/** Save good setup and Reconfigure (spec 4.3, 4.4): this router's saved setup, or another router's without its
 *  SIM PIN, put back through the usual preview and the 60 s rollback. */
export function SetupsBlock({ routerId, works, onApplied }: Props) {
  const client = useQueryClient()
  const setups = useQuery({ queryKey: ['lte-setups'], queryFn: () => apiFetch<LteSetupSummary[]>('/api/lte-setups') })
  const [source, setSource] = useState('')
  const [saveError, setSaveError] = useState<string | null>(null)
  const list = setups.data ?? []
  const own = list.find((s) => s.router_id === routerId && s.readable)
  const sorted = [...list].sort((a, b) => Number(b.router_id === routerId) - Number(a.router_id === routerId))
  const change = usePlanApply(`/api/routers/${routerId}/lte/setup`, source ? { source } : null, (result) => {
    setSource('')
    onApplied(result)
  })

  async function save() {
    if (own && !window.confirm(`Replace the good setup saved ${day(own)}?`)) return
    setSaveError(null)
    try {
      await postJson<LteSetupSummary>(`/api/routers/${routerId}/lte/setup`)
      await client.invalidateQueries({ queryKey: ['lte-setups'] })
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="stack" aria-label="Saved setups">
      <div className="row">
        <button type="button" onClick={() => void save()} disabled={!works} title={works ? undefined : SAVE_WHEN}>
          Save good setup
        </button>
        <label className="row" style={{ gap: 6 }}>
          <span>Reconfigure from</span>
          <select
            className="in"
            aria-label="Reconfigure from"
            value={source}
            onChange={(e) => {
              change.clear()
              setSource(e.target.value)
            }}
          >
            <option value="">Choose a saved setup…</option>
            {sorted.map((s) => (
              <option key={s.router_id} value={s.router_id} disabled={!s.readable}>
                {label(s, routerId)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {saveError && <div role="alert" className="note x">{saveError}</div>}
      <NetChange change={change} short={routerId} helpTopic={HELP.netRollback} show={source !== ''} />
    </div>
  )
}
