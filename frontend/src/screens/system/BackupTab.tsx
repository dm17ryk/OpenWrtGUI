import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch, downloadFile, postJson } from '../../api/client'
import type { BackupFile, NetPlan, RebootJob } from '../../api/types'
import { PreviewApply } from '../../components/PreviewApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'

const POLL_MS = 2000

function kib(bytes: number): string {
  return bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KiB` : `${(bytes / 1048576).toFixed(1)} MiB`
}

const errorText = (err: unknown): string => (err instanceof ApiError ? err.detail : String(err))

type Props = { routerId: string; routerName: string }

function BackupCard({ routerId, short }: { routerId: string; short: string }) {
  const client = useQueryClient()
  const list = useQuery({ queryKey: ['system-backups', routerId], queryFn: () => apiFetch<BackupFile[]>(`/api/routers/${routerId}/system/backups`) })
  const [isBusy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const act = async (work: () => Promise<unknown>): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      await work()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  const create = (): Promise<void> =>
    act(async () => {
      await postJson<BackupFile>(`/api/routers/${routerId}/system/backup`)
      await client.invalidateQueries({ queryKey: ['system-backups', routerId] })
    })
  return (
    <section className="card stack" aria-labelledby="system-backup-h">
      <div className="row">
        <div className="hrow">
          <h2 id="system-backup-h">Backup</h2>
          <Help topic={HELP.systemBackup} />
        </div>
        <div className="spacer" />
        <button type="button" className="btn pri" disabled={isBusy} onClick={() => void create()}>
          {isBusy ? 'Saving…' : 'Create backup'}
        </button>
      </div>
      <div className="note w">
        A backup holds the router&apos;s password hash, its SSH host keys, this app&apos;s key and the Wi-Fi keys: keep it like a password. It is saved
        in the app&apos;s data folder, readable by your Windows user only.
      </div>
      {error && <div className="note x">{error}</div>}
      {list.error && <div className="note x">{errorText(list.error)}</div>}
      {list.data && list.data.length === 0 && <div className="muted">{`No backups of ${short} saved yet.`}</div>}
      {list.data && list.data.length > 0 && (
        <div className="scroll-x">
          <table className="tbl" aria-label="Backups">
            <thead>
              <tr>
                <th>File</th>
                <th>Size</th>
                <th>Saved</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.map((b) => (
                <tr key={b.name}>
                  <td className="mono">{b.name}</td>
                  <td className="mono">{kib(b.size)}</td>
                  <td>{new Date(b.created_at).toLocaleString()}</td>
                  <td>
                    <button type="button" className="btn" onClick={() => void act(() => downloadFile(`/api/routers/${routerId}/system/backups/${b.name}`, b.name))}>
                      Download
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function phaseText(job: RebootJob, short: string): string {
  if (job.phase === 'armed') return `Armed: ${short} reboots in 2 s`
  if (job.phase === 'waiting') return `Waiting for ${short} to answer with a fresh uptime…`
  if (job.phase === 'back') return job.detail ?? `${short} is back`
  return job.error ?? `${short} is not back`
}

function RebootCard({ routerId, short }: { routerId: string; short: string }) {
  const client = useQueryClient()
  const [plan, setPlan] = useState<NetPlan | null>(null)
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isBusy, setBusy] = useState(false)
  const job = useQuery({
    queryKey: ['system-reboot', routerId],
    queryFn: () => apiFetch<RebootJob | null>(`/api/routers/${routerId}/system/reboot`),
    refetchInterval: (q) => (q.state.data && (q.state.data.phase === 'armed' || q.state.data.phase === 'waiting') ? POLL_MS : false),
  })
  const running = job.data != null && (job.data.phase === 'armed' || job.data.phase === 'waiting')
  const preview = async (): Promise<void> => {
    setError(null)
    try {
      setPlan(await postJson<NetPlan>(`/api/routers/${routerId}/system/reboot/preview`))
    } catch (err) {
      setError(errorText(err))
    }
  }
  const start = async (): Promise<void> => {
    if (!plan) return
    setAsking(false)
    setBusy(true)
    setError(null)
    try {
      const armed = await postJson<RebootJob>(`/api/routers/${routerId}/system/reboot/start`, { digest: plan.digest })
      client.setQueryData(['system-reboot', routerId], armed) // polling starts from the armed job
      setPlan(null)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="card stack" aria-labelledby="system-reboot-h">
      <div className="row">
        <div className="hrow">
          <h2 id="system-reboot-h">Reboot</h2>
          <Help topic={HELP.systemReboot} />
        </div>
        <div className="spacer" />
        {!plan && (
          <button type="button" className="btn" disabled={running} onClick={() => void preview()}>
            Preview reboot
          </button>
        )}
      </div>
      {plan && !running && (
        <PreviewApply
          heading={`Commands that will run on ${short}`}
          lines={plan.lines}
          warnings={plan.warnings}
          error={error}
          isBusy={isBusy}
          applyLabel={`Reboot ${short}`}
          onApply={() => setAsking(true)}
          helpTopic={HELP.systemReboot}
        />
      )}
      {!plan && error && <div className="note x">{error}</div>}
      {asking && (
        <div className="note w row" role="group" aria-label="Confirm reboot">
          <span>{`${short} goes offline for about a minute. Reboot it now?`}</span>
          <div className="spacer" />
          <button className="btn pri" type="button" onClick={() => void start()}>
            Reboot now
          </button>
          <button className="btn" type="button" onClick={() => setAsking(false)}>
            Cancel
          </button>
        </div>
      )}
      {job.data && (
        <div className={job.data.phase === 'not back' ? 'note x' : job.data.phase === 'back' ? 'note' : 'note w'} role="status" aria-label="Reboot">
          {phaseText(job.data, short)}
        </div>
      )}
    </section>
  )
}

/** The configuration archive (D9) and a reboot proven by a fresh uptime (D8). */
export function BackupTab({ routerId, routerName }: Props) {
  const short = routerName.split(' · ')[0] || routerId
  return (
    <>
      <BackupCard routerId={routerId} short={short} />
      <RebootCard routerId={routerId} short={short} />
    </>
  )
}
