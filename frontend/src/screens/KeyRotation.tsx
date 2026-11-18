import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { ApiError, apiFetch, postJson } from '../api/client'
import type { RotationJob, RotationPreview, RouterMove } from '../api/types'

const POLL_MS = 1000
const JOB_KEY = ['app-key-rotation']

const STATE: Record<RouterMove['state'], string> = {
  waiting: 'still on the old key',
  adding: 'adding the new key',
  proving: 'logging in with the new key',
  removing: 'removing the old key',
  moved: 'moved',
  failed: 'failed',
}

function status(job: RotationJob): string {
  const moved = job.routers.filter((r) => r.state === 'moved').length
  if (job.phase === 'running') return `Moving the app key: ${moved} of ${job.routers.length} routers done.`
  if (job.phase === 'done') return 'Rotated: every router logs in with the new key. The old private key is deleted.'
  return `${job.routers.length - moved} router(s) still on the old key. The old key stays on this PC until every router has the new one.`
}

function stateText(row: RouterMove): string {
  return row.detail ? `${STATE[row.state]}: ${row.detail}` : STATE[row.state]
}

/** Settings › App SSH key › Rotate key (v1.1b, spec 7.12, D8): the preview, then router by router. */
export function KeyRotation() {
  const client = useQueryClient()
  const job = useQuery({
    queryKey: JOB_KEY,
    queryFn: () => apiFetch<RotationJob | null>('/api/app-key/rotation'),
    refetchInterval: (q) => (q.state.data?.phase === 'running' ? POLL_MS : false),
  })
  const [preview, setPreview] = useState<RotationPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const current = job.data ?? null
  const running = current?.phase === 'running'

  useEffect(() => {
    if (current?.phase === 'done') void client.invalidateQueries({ queryKey: ['app-key'] })
  }, [current?.phase, current?.new_fingerprint, client])

  async function act(work: () => Promise<void>): Promise<void> {
    setError(null)
    setBusy(true)
    try {
      await work()
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e))
    } finally {
      setBusy(false)
    }
  }

  const showJob = (next: RotationJob): void => {
    client.setQueryData(JOB_KEY, next)
  }

  return (
    <div className="stack">
      {preview ? (
        <section className="stack" aria-label="Rotation preview">
          <ul className="stack">
            {preview.lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          {preview.warnings.map((w) => (
            <p key={w} className="note">
              {w}
            </p>
          ))}
          <div className="hrow">
            <button
              className="btn"
              type="button"
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  showJob(await postJson<RotationJob>('/api/app-key/rotation', { digest: preview.digest }))
                  setPreview(null)
                })
              }
            >
              Start
            </button>
            <button className="btn" type="button" disabled={busy} onClick={() => setPreview(null)}>
              Cancel
            </button>
          </div>
        </section>
      ) : (
        <div>
          <button
            className="btn"
            type="button"
            disabled={busy || running}
            onClick={() => void act(async () => setPreview(await postJson<RotationPreview>('/api/app-key/rotation/preview')))}
          >
            Rotate key…
          </button>
        </div>
      )}
      {current && (
        <>
          <p role="status">{status(current)}</p>
          {current.detail && <p className="note">{current.detail}</p>}
          <div className="scroll-x">
            <table className="tbl" aria-label="Key rotation">
              <thead>
                <tr>
                  <th>Router</th>
                  <th>State</th>
                  <th>
                    <span className="sr-only">Action</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {current.routers.map((row) => (
                  <tr key={row.router_id}>
                    <td>{row.name}</td>
                    <td>{stateText(row)}</td>
                    <td>
                      {!running && (row.state === 'failed' || row.state === 'waiting') && (
                        <button
                          className="btn"
                          type="button"
                          disabled={busy}
                          onClick={() =>
                            void act(async () => showJob(await postJson<RotationJob>(`/api/app-key/rotation/${row.router_id}/retry`)))
                          }
                        >
                          Retry
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {running && (
            <div>
              <button
                className="btn"
                type="button"
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    await postJson('/api/app-key/rotation/stop')
                    await client.invalidateQueries({ queryKey: JOB_KEY })
                  })
                }
              >
                Stop
              </button>
            </div>
          )}
        </>
      )}
      {error && (
        <p role="alert" className="note x">
          {error}
        </p>
      )}
    </div>
  )
}
