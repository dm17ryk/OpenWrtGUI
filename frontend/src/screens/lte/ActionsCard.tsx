import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { apiFetch } from '../../api/client'
import type { GuardOut, LteAction, NetApplyResult } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { guardReasonText } from '../../shell/guardText'
import { NetChange } from '../net/NetChange'

const ACTIONS: ReadonlyArray<readonly [LteAction, string]> = [
  ['connect', 'Connect'],
  ['disconnect', 'Disconnect'],
  ['reboot', 'Reboot modem'],
]

type Props = { routerId: string; routerName: string; onDone: (result: NetApplyResult) => void }

/** Connect, disconnect and the safe modem reboot, each with its exact commands first (v0.6a plan D6). */
export function ActionsCard({ routerId, routerName, onDone }: Props) {
  const short = routerName.split(' · ')[0] || routerId
  const guard = useQuery({ queryKey: ['guard'], queryFn: () => apiFetch<GuardOut>('/api/guard') })
  const live = guard.data?.live ?? false
  const [action, setAction] = useState<LteAction | null>(null)
  const change = usePlanApply(`/api/routers/${routerId}/lte/action`, action ? { action } : null, onDone)
  const label = ACTIONS.find(([a]) => a === action)?.[1] ?? ''
  const waiting = change.result?.checks.some((c) => c.name === 'lte_4 address' && c.ok === null) ?? false
  const runTitle = live && guard.data ? `Waits for the run: ${guardReasonText(guard.data)}` : undefined

  return (
    <section className="card stack" aria-labelledby="lte-actions-h">
      <div className="hrow">
        <h2 id="lte-actions-h">Connect, disconnect, reboot</h2>
        <Help topic={HELP.lteActions} />
      </div>
      {live && guard.data && (
        <div className="note w">A harness run is live ({guardReasonText(guard.data)}): Connect, Disconnect and Reboot modem wait for it to end.</div>
      )}
      <div className="seg" role="group" aria-label="LTE action">
        {ACTIONS.map(([a, text]) => (
          <button
            key={a}
            type="button"
            className={action === a ? 'on' : ''}
            aria-pressed={action === a}
            disabled={live}
            title={runTitle}
            onClick={() => {
              change.clear()
              setAction(action === a ? null : a)
            }}
          >
            {text}
          </button>
        ))}
      </div>
      <span className="muted">Reset to factory defaults is not offered yet (open item O1).</span>
      <NetChange change={change} short={short} helpTopic={HELP.lteActions} show={action !== null} applyLabel={`Run: ${label}`} provenText="Applied and checked" />
      {waiting && <div className="note">No address yet: waiting for the carrier's DHCP. The session is up; the address follows.</div>}
    </section>
  )
}
