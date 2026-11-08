import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch, postJson } from '../../api/client'
import type { ChecklistInfo, CopyIn, DiscoveryState, OverlayEntry, RouterItem } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

type Props = { routerId: string; state: DiscoveryState }

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`
}

type RowsProps = {
  title: string
  entries: OverlayEntry[]
  kept: Set<string>
  ticked: Set<string>
  onTick: (path: string) => void
}

function Rows({ title, entries, kept, ticked, onTick }: RowsProps) {
  if (entries.length === 0) return null
  return (
    <div className="stack" style={{ gap: 4 }}>
      <div className="eyebrow">{title}</div>
      <ul className="plain">
        {entries.map((e) => (
          <li key={e.path} className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            <label className="row" style={{ gap: 6, minWidth: 0 }}>
              <input type="checkbox" aria-label={e.path} checked={ticked.has(e.path)} onChange={() => onTick(e.path)} />
              <span className="mono" style={{ overflowWrap: 'anywhere' }}>
                {e.path}
              </span>
            </label>
            {e.target && <span className="muted">→ {e.target}</span>}
            <span className={kept.has(e.path) ? 'b air' : 'b park'}>{kept.has(e.path) ? 'kept on a flash' : 'lost on a flash'}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Added after flashing (spec 7.8): files and packages the image does not have, copies, the reflash checklist. */
export function OverlaySection({ routerId, state }: Props) {
  const client = useQueryClient()
  const routers = useQuery({ queryKey: ['routers'], queryFn: () => apiFetch<RouterItem[]>('/api/routers') })
  const [ticked, setTicked] = useState<Set<string>>(new Set())
  const [target, setTarget] = useState('')
  const [saved, setSaved] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const kept = new Set(state.kept_on_flash)
  const { overlay, packages } = state
  const tick = (path: string): void => {
    const next = new Set(ticked)
    if (next.has(path)) next.delete(path)
    else next.add(path)
    setTicked(next)
  }
  const body: CopyIn | null = ticked.size > 0 && target ? { paths: [...ticked], target } : null
  const copy = usePlanApply(`/api/routers/${routerId}/discovery/copy`, body, () => {
    setTicked(new Set())
    void client.invalidateQueries({ queryKey: ['discovery', target] })
  })
  const save = async (): Promise<void> => {
    setError(null)
    try {
      const c = await postJson<ChecklistInfo>(`/api/routers/${routerId}/discovery/checklist`)
      setSaved(`Saved: ${plural(c.lost.length, 'file', 'files')} lost on a flash`)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err))
    }
  }
  const nothing = overlay.added.length + overlay.replaced.length + overlay.deleted.length === 0
  return (
    <section className="card stack" aria-labelledby="ovl-h">
      <div className="hrow">
        <h2 id="ovl-h">Added after flashing</h2>
        <Help topic={HELP.overlay} />
      </div>
      {!state.has_overlay && <div className="muted">This router has no overlay.</div>}
      {nothing && state.has_overlay && <div className="muted">Nothing changed since flashing.</div>}
      <Rows title="Added" entries={overlay.added} kept={kept} ticked={ticked} onTick={tick} />
      <Rows title="Changed from the image" entries={overlay.replaced} kept={kept} ticked={ticked} onTick={tick} />
      {overlay.deleted.length > 0 && (
        <div className="stack" style={{ gap: 4 }}>
          <div className="eyebrow">Deleted from the image</div>
          <ul className="plain">
            {overlay.deleted.map((p) => (
              <li key={p} className="mono" style={{ overflowWrap: 'anywhere' }}>
                {p}
              </li>
            ))}
          </ul>
        </div>
      )}
      {overlay.unreadable > 0 && <div className="note w">{plural(overlay.unreadable, 'name', 'names')} could not be read</div>}
      {(packages.added.length > 0 || packages.removed.length > 0 || packages.changed.length > 0) && (
        <div className="stack" style={{ gap: 4 }}>
          <div className="eyebrow">Packages</div>
          {packages.added.map((p) => (
            <div key={p.name}>
              added: {p.name} {p.version}
            </div>
          ))}
          {packages.removed.map((name) => (
            <div key={name}>removed: {name}</div>
          ))}
          {packages.changed.map(([name, image, router]) => (
            <div key={name}>
              changed: {name} {image} → {router}
            </div>
          ))}
        </div>
      )}
      <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
        <HelpTip topic={HELP.copyFiles}>
          <label className="row" style={{ gap: 6 }}>
            Copy to
            <select aria-label="Copy to" value={target} disabled={ticked.size === 0} onChange={(e) => setTarget(e.target.value)}>
              <option value="">pick a router</option>
              {(routers.data ?? [])
                .filter((r) => r.record.auth === 'key')
                .map((r) => (
                  <option key={r.record.id} value={r.record.id}>
                    {r.record.name}
                    {r.record.id === routerId ? ' (this router)' : ''}
                  </option>
                ))}
            </select>
          </label>
        </HelpTip>
        <span className="spacer" />
        <HelpTip topic={HELP.checklist}>
          <button className="btn" type="button" onClick={() => void save()}>
            Save as reflash checklist
          </button>
        </HelpTip>
      </div>
      <NetChange change={copy} short={target || routerId} helpTopic={HELP.copyFiles} show={body !== null} applyLabel="Copy" provenText="Copied and proven" />
      {saved && <div className="note">{saved}</div>}
      {error && <div className="note x">{error}</div>}
    </section>
  )
}
