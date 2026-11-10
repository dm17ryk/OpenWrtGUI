import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch, downloadFile, postBytes, postJson } from '../../api/client'
import type { BackupFile, NetPlan, RebootJob } from '../../api/types'
import { PreviewApply } from '../../components/PreviewApply'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import { JobStatus } from './JobStatus'
import { KeptFilesCard } from './KeptFilesCard'
import { ResetCard } from './ResetCard'
import { RestoreCard } from './RestoreCard'
import { isRunning, useJob, useJobEnd, useStartJob } from './useJob'

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
  // a file from the PC: checked by the app (nothing goes to the router), then listed like a saved backup
  const pick = (file: File | undefined): Promise<void> =>
    act(async () => {
      if (!file) return
      await postBytes<BackupFile>(`/api/routers/${routerId}/system/backups/import`, await file.arrayBuffer(), file.name)
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
        <HelpTip topic={HELP.systemImport}>
          <label className="btn">
            Import backup…
            <input type="file" accept=".tar.gz,.tgz" aria-label="Import backup…" hidden disabled={isBusy} onChange={(e) => void pick(e.target.files?.[0])} />
          </label>
        </HelpTip>
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
                  <td>
                    <span className="mono">{b.name}</span>
                    {b.imported && <div className="muted">imported from this PC</div>}
                  </td>
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

function RebootCard({ routerId, short }: { routerId: string; short: string }) {
  const [plan, setPlan] = useState<NetPlan | null>(null)
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isBusy, setBusy] = useState(false)
  const job = useJob(routerId)
  const startJob = useStartJob(routerId)
  const running = isRunning(job.data)
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
      startJob(armed)
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
      {job.data?.kind === 'reboot' && <JobStatus job={job.data} short={short} label="Reboot" />}
    </section>
  )
}

/** The configuration archive and its import, restore and kept files, a reboot proven by a fresh uptime, and
 * the reset to defaults (v0.6b D8-D9, v0.6c D10-D12). One job (reboot, restore, reset) runs at a time. */
export function BackupTab({ routerId, routerName }: Props) {
  const short = routerName.split(' · ')[0] || routerId
  useJobEnd(routerId)
  return (
    <>
      <BackupCard routerId={routerId} short={short} />
      <RestoreCard routerId={routerId} short={short} />
      <KeptFilesCard routerId={routerId} short={short} />
      <RebootCard routerId={routerId} short={short} />
      <ResetCard routerId={routerId} routerName={routerName} />
    </>
  )
}
