import { useState } from 'react'
import { Link } from 'react-router'
import { ApiError, postJson } from '../../api/client'
import type { NetPlan, RebootJob } from '../../api/types'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import { JobStatus } from './JobStatus'
import { isRunning, useJob, useStartJob } from './useJob'

const errorText = (err: unknown): string => (err instanceof ApiError ? err.detail : String(err))

type Props = { routerId: string; routerName: string }

/**
 * Reset to defaults (D12): `firstboot -r -y` through the router's timer. Start waits for the router's name,
 * typed, and the tick that it is alone on this PC's network; afterwards the router is to be added again.
 */
export function ResetCard({ routerId, routerName }: Props) {
  const short = routerName.split(' · ')[0] || routerId
  const base = `/api/routers/${routerId}/system/reset`
  const job = useJob(routerId)
  const startJob = useStartJob(routerId)
  const [plan, setPlan] = useState<NetPlan | null>(null)
  const [typed, setTyped] = useState('')
  const [isAlone, setAlone] = useState(false)
  const [isBusy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const running = isRunning(job.data)
  const isReady = typed === routerName && isAlone
  const preview = async (): Promise<void> => {
    setError(null)
    try {
      setPlan(await postJson<NetPlan>(`${base}/preview`))
    } catch (err) {
      setError(errorText(err))
    }
  }
  const start = async (): Promise<void> => {
    if (!plan || !isReady) return
    setBusy(true)
    setError(null)
    try {
      startJob(await postJson<RebootJob>(`${base}/start`, { digest: plan.digest, confirm_name: typed, alone: isAlone }))
      setPlan(null)
      setTyped('')
      setAlone(false)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  const ours = job.data?.kind === 'reset' ? job.data : null
  return (
    <section className="card stack" aria-labelledby="system-reset-h">
      <div className="row">
        <div className="hrow">
          <h2 id="system-reset-h">Reset to defaults</h2>
          <Help topic={HELP.systemReset} />
        </div>
        <div className="spacer" />
        {!plan && (
          <button type="button" className="btn" disabled={running} onClick={() => void preview()}>
            Preview reset
          </button>
        )}
      </div>
      <div className="muted">Erases every setting: {short} comes back like a new router, at 192.168.1.1 with no password.</div>
      {plan && !running && (
        <div className="stack" style={{ gap: 10 }}>
          <div className="eyebrow">{`Commands that will run on ${short}`}</div>
          <div className="code" role="region" aria-label="Command preview" tabIndex={0}>
            {plan.lines.join('\n')}
          </div>
          {plan.warnings.map((w) => (
            <div key={w} className="note w">
              {w}
            </div>
          ))}
          <label className="field">
            <span>{`Type ${routerName} to confirm`}</span>
            <input className="in" value={typed} autoComplete="off" onChange={(e) => setTyped(e.target.value)} />
          </label>
          <label className="row" style={{ gap: 6 }}>
            <input type="checkbox" checked={isAlone} onChange={(e) => setAlone(e.target.checked)} />
            {`${routerName} is alone on this PC's network`}
          </label>
          {error && (
            <div className="note x" role="alert">
              {error}
            </div>
          )}
          <div className="row">
            <HelpTip topic={HELP.systemReset}>
              <button className="btn pri" type="button" disabled={!isReady || isBusy} onClick={() => void start()}>
                {isBusy ? 'Starting…' : 'Start reset'}
              </button>
            </HelpTip>
            <button className="btn" type="button" onClick={() => setPlan(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {!plan && error && <div className="note x">{error}</div>}
      {ours && <JobStatus job={ours} short={short} label="Reset" />}
      {ours?.phase === 'reset' && (
        <div className="note row">
          <span>{`${routerName} now answers at 192.168.1.1 with no password and a new host key: add it again.`}</span>
          <div className="spacer" />
          <Link className="btn" to="/add?host=192.168.1.1">
            Add again
          </Link>
        </div>
      )}
    </section>
  )
}
