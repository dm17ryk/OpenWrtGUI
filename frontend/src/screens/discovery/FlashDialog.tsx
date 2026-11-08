import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { ApiError, apiFetch, postJson } from '../../api/client'
import type { FlashJob, FlashPlanOut, ProfileOut } from '../../api/types'
import { PreviewApply } from '../../components/PreviewApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { usePreview } from '../wifi/usePreview'
import { CopyBack } from './CopyBack'

type Props = { routerId: string; routerName: string; board: string; revision: string; pollMs?: number; onClose: () => void }

const isRunning = (job: FlashJob | null | undefined): boolean => !!job && job.phase !== 'done' && job.phase !== 'failed'

function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

function kib(bytes: number): string {
  return bytes >= 2 ** 20 ? `${(bytes / 2 ** 20).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`
}

/** "Type AP2" or "AP2 · office": either the short name or the whole one, in any case. */
function isNamed(typed: string, name: string): boolean {
  const t = typed.trim().toLowerCase()
  return t !== '' && (t === name.toLowerCase() || t === name.split(' · ')[0].toLowerCase())
}

function Progress({ job, name }: { job: FlashJob; name: string }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (job.phase !== 'wait') return undefined
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [job.phase])
  if (job.phase === 'upload') {
    const pct = job.total > 0 ? Math.floor((job.sent / job.total) * 100) : 0
    return (
      <div className="stack" style={{ gap: 4 }}>
        <span>Sending the image: {pct} %</span>
        <progress aria-label="Upload" value={job.sent} max={job.total} />
      </div>
    )
  }
  const text: Record<string, string> = {
    check: `Checking the image on ${name}`,
    arm: 'Starting sysupgrade',
    wait: `Waiting for ${name} to come back (${clock((now - Date.parse(job.started_at)) / 1000)})`,
    prove: 'Checking the new firmware',
  }
  if (job.phase in text) return <div role="status">{text[job.phase]}</div>
  if (job.phase === 'failed') return <div className="note x">{job.error ?? 'The flash failed'}</div>
  return <div className="note">{job.detail ?? 'Flashed'}</div>
}

/** Flash this router with an imported image (spec 7.11): exact preview, the typed name, progress, copy back. */
export function FlashDialog({ routerId, routerName, board, revision, pollMs = 1000, onClose }: Props) {
  const client = useQueryClient()
  const images = useQuery({ queryKey: ['images'], queryFn: () => apiFetch<ProfileOut[]>('/api/images') })
  const job = useQuery({
    queryKey: ['flash', routerId],
    queryFn: () => apiFetch<FlashJob | null>(`/api/routers/${routerId}/flash`),
    refetchInterval: (q) => (isRunning(q.state.data) ? pollMs : false),
  })
  const [folder, setFolder] = useState<string | null>(null)
  const [keep, setKeep] = useState(true)
  const [isolated, setIsolated] = useState(false)
  const [typed, setTyped] = useState('')
  const [startError, setStartError] = useState<string | null>(null)
  const [isStarting, setStarting] = useState(false)
  const [keptSettings, setKeptSettings] = useState(true)
  const [isCopying, setCopying] = useState(false)
  const candidates = (images.data ?? []).filter((p) => p.source === 'image' && p.boards.includes(board))
  const chosen = candidates.find((p) => p.folder === folder) ?? candidates.find((p) => p.revision !== revision) ?? candidates[0] ?? null
  const current = job.data ?? null
  const isBusy = isRunning(current)
  const body =
    chosen && (keep || isolated) && !isBusy
      ? { board: chosen.key.board, revision: chosen.key.revision, sha256: chosen.key.sha256, keep_settings: keep, isolated }
      : null
  const preview = usePreview<FlashPlanOut>(`/api/routers/${routerId}/flash/preview`, body)
  const phase = current?.phase
  useEffect(() => {
    if (phase !== 'done' && phase !== 'failed') return
    void client.invalidateQueries({ queryKey: ['discovery', routerId] })
    void client.invalidateQueries({ queryKey: ['routers'] })
  }, [phase, client, routerId])
  const start = async (): Promise<void> => {
    const plan = preview?.plan
    if (!body || !plan) return
    setStarting(true)
    setStartError(null)
    try {
      const started = await postJson<FlashJob>(`/api/routers/${routerId}/flash/start`, { ...body, digest: plan.digest })
      setKeptSettings(keep)
      client.setQueryData(['flash', routerId], started)
    } catch (err) {
      setStartError(err instanceof ApiError ? err.detail : String(err))
    } finally {
      setStarting(false)
    }
  }
  const showForm = !current || (!isBusy && !isStarting && phase !== 'done')
  return (
    <section className="card stack" aria-labelledby="flash-h">
      <div className="hrow">
        <h2 id="flash-h">Flash {routerName}</h2>
        <Help topic={HELP.flash} />
        <span className="spacer" />
        <button className="btn" type="button" disabled={isBusy} onClick={onClose}>
          Close
        </button>
      </div>
      {current && <Progress job={current} name={routerName} />}
      {phase === 'done' && keptSettings && !isCopying && (
        <div>
          <button className="btn" type="button" onClick={() => setCopying(true)}>
            Copy back lost files
          </button>
        </div>
      )}
      {phase === 'done' && isCopying && <CopyBack routerId={routerId} routerName={routerName} />}
      {showForm && (
        <>
          {candidates.length === 0 ? (
            <div className="note">No imported image is for {board}. Import one in Settings › Images.</div>
          ) : (
            <label className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
              Image
              <select aria-label="Image" value={chosen?.folder ?? ''} onChange={(e) => setFolder(e.target.value)}>
                {candidates.map((p) => (
                  <option key={p.folder} value={p.folder}>
                    {p.label}
                    {p.revision === revision ? ' (running now)' : ''}
                  </option>
                ))}
              </select>
              {chosen && (
                <span className="muted">
                  {chosen.image_name} · {kib(chosen.image_size ?? 0)}
                </span>
              )}
            </label>
          )}
          <label className="row" style={{ gap: 6 }}>
            <input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} />
            Keep settings
          </label>
          {!keep && (
            <div className="stack" style={{ gap: 6 }}>
              <div className="note w">
                Without settings {routerName} comes back as 192.168.1.1 with no password and no key, the address AP1 uses. Connect it alone to this
                PC, then add it again; the wizard accepts its new key only if it reports this image’s board and revision.
              </div>
              <label className="row" style={{ gap: 6 }}>
                <input type="checkbox" checked={isolated} onChange={(e) => setIsolated(e.target.checked)} />I have isolated {routerName} from the bench
                LAN
              </label>
            </div>
          )}
          {body && (
            <>
              <label className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
                Type the router’s name to flash it
                <input value={typed} placeholder={routerName.split(' · ')[0]} onChange={(e) => setTyped(e.target.value)} />
              </label>
              <PreviewApply
                heading={`Commands that will run on ${routerName}`}
                lines={preview?.plan?.lines ?? []}
                warnings={preview?.plan?.warnings ?? []}
                error={startError ?? preview?.error ?? null}
                isBusy={isStarting}
                isDisabled={!isNamed(typed, routerName)}
                applyLabel="Flash"
                onApply={() => void start()}
                helpTopic={HELP.flash}
              />
            </>
          )}
        </>
      )}
    </section>
  )
}
