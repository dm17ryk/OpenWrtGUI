import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { apiFetch, postJson } from '../../api/client'
import type { GuardOut, LteAction, LteRecoverJob, NetApplyResult, RecoverPreview } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { guardReasonText } from '../../shell/guardText'
import { NetChange } from '../net/NetChange'
import { RecoverPanel } from './RecoverPanel'
import { isRecovering, useLteRecover } from './useLteRecover'

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
      <span className="muted">The stock firmware's "Restore modem defaults" only turns the modem's autoconnect off; Recover's fourth step does the same.</span>
      <NetChange change={change} short={short} helpTopic={HELP.lteActions} show={action !== null} applyLabel={`Run: ${label}`} provenText="Applied and checked" />
      {waiting && <div className="note">No address yet: waiting for the carrier's DHCP. The session is up; the address follows.</div>}
      <RecoverStart routerId={routerId} live={live} runTitle={runTitle} />
    </section>
  )
}

/** Recover (spec 4.2): its preview of every command it may run, then Start; the panel shows the job. */
function RecoverStart({ routerId, live, runTitle }: { routerId: string; live: boolean; runTitle?: string }) {
  const client = useQueryClient()
  const recover = useLteRecover(routerId)
  const job = recover.data ?? null
  const [preview, setPreview] = useState<RecoverPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const running = isRecovering(job)
  const base = `/api/routers/${routerId}/lte/recover`
  // when a job ends, the Status card and Save good setup read the modem again (PR #82 review)
  const phase = job?.phase
  const was = useRef(phase)
  useEffect(() => {
    if (was.current === 'running' && phase !== undefined && phase !== 'running') {
      for (const key of ['lte', 'lte-options', 'network']) void client.invalidateQueries({ queryKey: [key, routerId] })
    }
    was.current = phase
  }, [phase, client, routerId])

  async function show() {
    setError(null)
    try {
      setPreview(await postJson<RecoverPreview>(`${base}/preview`))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function start() {
    if (!preview) return
    setError(null)
    try {
      client.setQueryData(['lte-recover', routerId], await postJson<LteRecoverJob>(base, { digest: preview.digest }))
      setPreview(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <>
      <div className="row">
        <button type="button" onClick={() => void show()} disabled={live || running} title={running ? 'Recover is running' : runTitle}>
          Recover
        </button>
        <span className="muted">Finds what is wrong, then tries one step at a time until LTE works. It never reboots the router.</span>
      </div>
      {preview && (
        <section className="stack" aria-label="Recover preview">
          <div className="code" role="region" aria-label="Recover commands" tabIndex={0}>
            {preview.lines.join('\n')}
          </div>
          {preview.warnings.map((w) => (
            <div key={w} className="note w">
              {w}
            </div>
          ))}
          <div className="row">
            <button type="button" className="primary" onClick={() => void start()} disabled={live}>
              Start
            </button>
            <button type="button" onClick={() => setPreview(null)}>
              Cancel
            </button>
          </div>
        </section>
      )}
      {error && <div role="alert" className="note x">{error}</div>}
      {job && <RecoverPanel routerId={routerId} job={job} />}
    </>
  )
}
