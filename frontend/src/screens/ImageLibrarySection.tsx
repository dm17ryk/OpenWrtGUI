import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch, postJson } from '../api/client'
import type { LibraryEntryOut, LibraryOut, ProfileOut } from '../api/types'
import { megabytes } from '../format'
import { Help } from '../help/Help'
import { HELP } from '../help/topics'

const LIBRARY_KEY = ['library', 'all']

const readTime = (readAt: string): string =>
  new Date(readAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })

const detail = (err: unknown): string => (err instanceof ApiError ? err.detail : String(err))

/** Settings › Image library: every image the releases of dm17ryk/openwrt offer; nothing downloads without a click. */
export function ImageLibrarySection() {
  const client = useQueryClient()
  const library = useQuery({ queryKey: LIBRARY_KEY, queryFn: () => apiFetch<LibraryOut>('/api/images/library') })
  const [downloading, setDownloading] = useState<string | null>(null)
  const [isRefreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const afterImport = (): void => {
    void client.invalidateQueries({ queryKey: ['library'] })
    void client.invalidateQueries({ queryKey: ['images'] })
    void client.invalidateQueries({ queryKey: ['discovery'] })
  }
  const download = async (entry: LibraryEntryOut): Promise<void> => {
    setDownloading(entry.sha256)
    setError(null)
    try {
      await postJson<ProfileOut>(`/api/images/library/${entry.sha256}`)
      afterImport()
    } catch (err) {
      setError(detail(err))
    } finally {
      setDownloading(null)
    }
  }
  const refresh = async (): Promise<void> => {
    setRefreshing(true)
    setError(null)
    try {
      client.setQueryData(LIBRARY_KEY, await postJson<LibraryOut>('/api/images/library/refresh'))
    } catch (err) {
      setError(detail(err))
    } finally {
      setRefreshing(false)
    }
  }

  const data = library.data
  const skipped = data?.skipped ?? 0
  return (
    <section className="card stack" aria-labelledby="lib-h">
      <div className="hrow">
        <h2 id="lib-h">Image library</h2>
        <Help topic={HELP.imageLibrary} />
        <span className="spacer" />
        {data?.read_at && <span className="muted">{`Read at ${readTime(data.read_at)}`}</span>}
        <button className="btn" type="button" disabled={isRefreshing || downloading !== null} onClick={() => void refresh()}>
          {isRefreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      {library.isPending && <div className="muted">Looking in the image library…</div>}
      {library.isError && <div className="note x">{detail(library.error)}</div>}
      {data?.error && <div className="note x">{data.error}</div>}
      {data && !data.error && data.entries.length === 0 && <div className="muted">The image library lists no images.</div>}
      {data && data.entries.length > 0 && (
        <ul className="stack" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {data.entries.map((e) => (
            <li key={e.sha256} className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
              <div className="stack" style={{ gap: 2 }}>
                <strong>{e.title}</strong>
                <span className="muted">{`${e.boards.join(', ')} · ${e.revision} · ${megabytes(e.size)}`}</span>
                <span className="muted">
                  <a href={e.release_url} target="_blank" rel="noopener noreferrer">
                    {e.release_name}
                  </a>
                  {e.prerelease ? ' pre-release' : ''}
                </span>
              </div>
              <span className="spacer" />
              {e.imported ? (
                <span>Imported</span>
              ) : (
                <button className="btn" type="button" disabled={downloading !== null || isRefreshing} onClick={() => void download(e)}>
                  {downloading === e.sha256 ? 'Downloading…' : 'Download'}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {skipped > 0 && <div className="muted">{`${skipped} ${skipped === 1 ? 'release' : 'releases'} could not be read`}</div>}
      {error && <div className="note x">{error}</div>}
    </section>
  )
}
