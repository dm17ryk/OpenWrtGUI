import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch, postJson } from '../../api/client'
import type { LibraryOut, ProfileOut } from '../../api/types'
import { megabytes } from '../ImagesSection'

type Props = {
  board: string
  revision: string
  onImported: () => void
  disabled: boolean
  /** Lets the card disable its other buttons while the download runs. */
  onBusyChange?: (isBusy: boolean) => void
}

const plural = (n: number, one: string, many: string): string => (n === 1 ? one : many)

/** The build of this router's board and revision in the image library; downloading it is a click away. */
export function LibraryOffer({ board, revision, onImported, disabled, onBusyChange }: Props) {
  const library = useQuery({
    queryKey: ['library', board, revision],
    queryFn: () =>
      apiFetch<LibraryOut>(
        `/api/images/library?board=${encodeURIComponent(board)}&revision=${encodeURIComponent(revision)}`,
      ),
  })
  const [isBusy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (library.isPending) return <div className="muted">Looking in the image library…</div>
  if (library.isError) {
    const detail = library.error instanceof ApiError ? library.error.detail : String(library.error)
    return <div className="note x">{detail}</div>
  }
  const { entries, skipped, error: libraryError } = library.data
  const [entry, ...others] = entries
  const download = async (sha256: string): Promise<void> => {
    setBusy(true)
    onBusyChange?.(true)
    setError(null)
    try {
      await postJson<ProfileOut>(`/api/images/library/${sha256}`)
      onImported()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err))
    } finally {
      setBusy(false)
      onBusyChange?.(false)
    }
  }
  return (
    <div className="stack" style={{ gap: 6 }}>
      {libraryError && <div className="note x">{libraryError}</div>}
      {!libraryError && !entry && <div className="muted">The image library has no build for {board} {revision}.</div>}
      {entry && (
        <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
          <span>{`Image library: ${entry.title}, ${entry.revision}, ${megabytes(entry.size)}, release ${entry.release_name}`}</span>
          <span className="spacer" />
          <button className="btn" type="button" disabled={disabled || isBusy} onClick={() => void download(entry.sha256)}>
            {isBusy ? `Downloading ${megabytes(entry.size)}…` : 'Download and import'}
          </button>
        </div>
      )}
      {others.length > 0 && (
        <div className="muted">
          {`${others.length} ${plural(others.length, 'other build', 'other builds')} of this revision ${plural(others.length, 'is', 'are')} listed in Settings › Images; Check firmware tells whether the router runs the one you downloaded.`}
        </div>
      )}
      {skipped > 0 && <div className="muted">{`${skipped} ${plural(skipped, 'release', 'releases')} could not be read`}</div>}
      {error && <div className="note x">{error}</div>}
    </div>
  )
}
