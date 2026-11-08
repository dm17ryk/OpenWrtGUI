import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch, postBytes } from '../api/client'
import type { ProfileOut } from '../api/types'
import { Help, HelpTip } from '../help/Help'
import { HELP } from '../help/topics'

function megabytes(size: number | null): string {
  return size === null ? '' : `${(size / 2 ** 20).toFixed(1)} MB`
}

/** Send a sysupgrade file to the app; it is read on this PC, nothing goes to a router. */
async function importImage(file: File): Promise<ProfileOut> {
  return postBytes<ProfileOut>('/api/images', await file.arrayBuffer(), file.name)
}

type ImportProps = { onImported: (profile: ProfileOut) => void }

/** The file picker with its busy and error states (Settings › Images and Discovery's no-match note). */
export function ImportImage({ onImported }: ImportProps) {
  const [isBusy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pick = async (file: File | undefined): Promise<void> => {
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      onImported(await importImage(file))
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="stack">
      <HelpTip topic={HELP.routerFamily}>
        <label className="btn">
          {isBusy ? 'Reading the image…' : 'Import image…'}
          <input
            type="file"
            accept=".bin"
            aria-label="Import image…"
            hidden
            disabled={isBusy}
            onChange={(e) => void pick(e.target.files?.[0])}
          />
        </label>
      </HelpTip>
      {error && <div className="note x">{error}</div>}
    </div>
  )
}

/** Settings › Images (decision D12): the imported images and /rom profiles, import and delete. */
export function ImagesSection() {
  const client = useQueryClient()
  const images = useQuery({ queryKey: ['images'], queryFn: () => apiFetch<ProfileOut[]>('/api/images') })
  const [error, setError] = useState<string | null>(null)
  const refresh = (): void => {
    void client.invalidateQueries({ queryKey: ['images'] })
    void client.invalidateQueries({ queryKey: ['discovery'] })
  }
  const remove = async (p: ProfileOut): Promise<void> => {
    if (!window.confirm(`Delete ${p.label}${p.image_name ? ` (${p.image_name})` : ''}?`)) return
    try {
      await apiFetch(`/api/images/${encodeURIComponent(p.key.board)}/${encodeURIComponent(p.folder)}`, {
        method: 'DELETE',
      })
      refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err))
    }
  }
  const list = images.data ?? []
  return (
    <section className="card stack" aria-labelledby="img-h">
      <div className="hrow">
        <h2 id="img-h">Images</h2>
        <Help topic={HELP.images} />
      </div>
      {list.length === 0 && !images.isLoading && (
        <div className="muted">No image imported yet. Import a router's sysupgrade .bin to see what it changed since flashing.</div>
      )}
      {list.map((p) => (
        <div key={`${p.key.board}/${p.folder}`} className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
          <div className="stack" style={{ gap: 2 }}>
            <strong>{p.label}</strong>
            <span className="muted">
              {p.source === 'rom' ? 'from a router’s /rom' : `${p.image_name} · ${megabytes(p.image_size)}`}
              {p.custom.length > 0 ? ` · custom: ${p.custom.join(', ')}` : ''}
            </span>
          </div>
          <span className="spacer" />
          <button className="btn" type="button" onClick={() => void remove(p)}>
            Delete
          </button>
        </div>
      ))}
      <ImportImage onImported={refresh} />
      {error && <div className="note x">{error}</div>}
    </section>
  )
}
