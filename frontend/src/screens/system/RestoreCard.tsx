import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch, postJson } from '../../api/client'
import type { BackupFile, NetPlan, RebootJob, RestoreCheck } from '../../api/types'
import { PreviewApply } from '../../components/PreviewApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { JobStatus } from './JobStatus'
import { isRunning, useJob, useStartJob } from './useJob'

const errorText = (err: unknown): string => (err instanceof ApiError ? err.detail : String(err))

type Props = { routerId: string; short: string }

/**
 * A backup from the app's list put back on the router (D11): Check reads the archive and says what it
 * holds or why it is refused; the preview follows; Restore and reboot asks once more, then the job runs.
 */
export function RestoreCard({ routerId, short }: Props) {
  const base = `/api/routers/${routerId}/system`
  const list = useQuery({ queryKey: ['system-backups', routerId], queryFn: () => apiFetch<BackupFile[]>(`${base}/backups`) })
  const job = useJob(routerId)
  const startJob = useStartJob(routerId)
  const [picked, setPicked] = useState('')
  const [check, setCheck] = useState<RestoreCheck | null>(null)
  const [plan, setPlan] = useState<NetPlan | null>(null)
  const [isAsking, setAsking] = useState(false)
  const [isBusy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const backups = list.data ?? []
  const name = backups.some((b) => b.name === picked) ? picked : (backups[0]?.name ?? '')
  const running = isRunning(job.data)
  const reset = (): void => {
    setCheck(null)
    setPlan(null)
    setAsking(false)
    setError(null)
  }
  const runCheck = async (): Promise<void> => {
    reset()
    setPicked(name) // a backup listed meanwhile (it comes first) must not change what was checked
    setBusy(true)
    try {
      const found = await postJson<RestoreCheck>(`${base}/restore/check`, { name })
      setCheck(found)
      if (found.refusals.length === 0) setPlan(await postJson<NetPlan>(`${base}/restore/preview`, { name }))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  const start = async (): Promise<void> => {
    if (!plan) return
    setAsking(false)
    setBusy(true)
    setError(null)
    try {
      startJob(await postJson<RebootJob>(`${base}/restore/start`, { name, digest: plan.digest }))
      setCheck(null)
      setPlan(null)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="card stack" aria-labelledby="system-restore-h">
      <div className="hrow">
        <h2 id="system-restore-h">Restore</h2>
        <Help topic={HELP.systemRestore} />
      </div>
      {list.data && backups.length === 0 && <div className="muted">Create or import a backup of {short} first: only a backup in this list can be restored.</div>}
      {backups.length > 0 && (
        <div className="row">
          <label className="field">
            <span>Backup to restore</span>
            <select
              className="in mono"
              value={name}
              onChange={(e) => {
                setPicked(e.target.value)
                reset()
              }}
            >
              {backups.map((b) => (
                <option key={b.name} value={b.name}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="btn" disabled={isBusy || running} onClick={() => void runCheck()}>
            Check
          </button>
        </div>
      )}
      {check && check.refusals.length > 0 && (
        <div className="note x" role="alert">
          Not restored:
          <ul>
            {check.refusals.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      )}
      {check && check.refusals.length === 0 && (
        <div className="stack" style={{ gap: 6 }}>
          <div className="eyebrow">The backup holds</div>
          <ul aria-label="Files in the backup" className="mono">
            {check.files.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </div>
      )}
      {plan && !running && (
        <PreviewApply
          heading={`Commands that will run on ${short}`}
          lines={plan.lines}
          warnings={plan.warnings}
          error={error}
          isBusy={isBusy}
          applyLabel="Restore and reboot"
          onApply={() => setAsking(true)}
          helpTopic={HELP.systemRestore}
        />
      )}
      {!plan && error && <div className="note x">{error}</div>}
      {isAsking && (
        <div className="note w row" role="group" aria-label="Confirm restore">
          <span>{`${short} takes the backup's settings and reboots. Restore it now?`}</span>
          <div className="spacer" />
          <button className="btn pri" type="button" onClick={() => void start()}>
            Restore now
          </button>
          <button className="btn" type="button" onClick={() => setAsking(false)}>
            Cancel
          </button>
        </div>
      )}
      {job.data?.kind === 'restore' && <JobStatus job={job.data} short={short} label="Restore" />}
    </section>
  )
}
