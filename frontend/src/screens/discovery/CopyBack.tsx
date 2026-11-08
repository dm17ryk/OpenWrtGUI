import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { apiFetch } from '../../api/client'
import type { ChecklistInfo, CopyIn } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

/** After a flash: the files the last reflash checklist saved, all ticked, copied back to this router. */
export function CopyBack({ routerId, routerName }: { routerId: string; routerName: string }) {
  const client = useQueryClient()
  const checklists = useQuery({
    queryKey: ['checklists', routerId],
    queryFn: () => apiFetch<ChecklistInfo[]>(`/api/routers/${routerId}/discovery/checklists`),
  })
  const latest = checklists.data?.[0] ?? null
  const [unticked, setUnticked] = useState<Set<string>>(new Set())
  const paths = (latest?.restorable ?? []).filter((p) => !unticked.has(p))
  const body: CopyIn | null = latest && paths.length > 0 ? { paths, target: routerId, from_checklist: latest.stamp } : null
  const copy = usePlanApply(`/api/routers/${routerId}/discovery/copy`, body, () => {
    void client.invalidateQueries({ queryKey: ['discovery', routerId] })
  })
  const toggle = (path: string): void => {
    const next = new Set(unticked)
    if (next.has(path)) next.delete(path)
    else next.add(path)
    setUnticked(next)
  }
  if (checklists.isPending) return <div className="muted">Reading the reflash checklist…</div>
  if (!latest) return <div className="note">No reflash checklist was saved for {routerName}.</div>
  const unsaved = latest.lost.filter((p) => !latest.restorable.includes(p))
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="eyebrow">Checklist {latest.stamp}: files the flash lost</div>
      <ul className="plain">
        {latest.restorable.map((p) => (
          <li key={p}>
            <label className="row" style={{ gap: 6 }}>
              <input type="checkbox" aria-label={p} checked={!unticked.has(p)} onChange={() => toggle(p)} />
              <span className="mono" style={{ overflowWrap: 'anywhere' }}>
                {p}
              </span>
            </label>
          </li>
        ))}
      </ul>
      {unsaved.length > 0 && <div className="note w">Not saved (too big or unreadable): {unsaved.join(', ')}</div>}
      <NetChange change={copy} short={routerName} helpTopic={HELP.copyFiles} show={body !== null} applyLabel="Copy back" provenText="Copied back and proven" />
    </div>
  )
}
