import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch } from '../../api/client'
import type { KeptFiles } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

function KeptForm({ routerId, short, kept }: { routerId: string; short: string; kept: KeptFiles }) {
  const client = useQueryClient()
  const [seen, setSeen] = useState(kept.text)
  const [draft, setDraft] = useState(kept.text)
  if (seen !== kept.text) {
    // the router's list changed (an apply, a read again): start from it
    setSeen(kept.text)
    setDraft(kept.text)
  }
  const body = draft !== kept.text ? { text: draft } : null
  const change = usePlanApply(`/api/routers/${routerId}/system/kept-files`, body, () => {
    void client.invalidateQueries({ queryKey: ['system-kept', routerId] })
  })
  return (
    <>
      <div className="grid">
        <label className="field">
          <span>Files kept in a backup (/etc/sysupgrade.conf)</span>
          <textarea className="in mono" rows={8} spellCheck={false} value={draft} onChange={(e) => setDraft(e.target.value)} />
        </label>
        <div className="stack" style={{ gap: 6 }}>
          <div className="eyebrow">A backup holds now</div>
          {kept.listed.length === 0 ? (
            <div className="muted">{short} lists no files for a backup.</div>
          ) : (
            <ul aria-label="Files a backup holds" className="mono">
              {kept.listed.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <NetChange change={change} short={short} helpTopic={HELP.systemKept} show={body !== null} />
    </>
  )
}

type Props = { routerId: string; short: string }

/** /etc/sysupgrade.conf (D10): the extra files and folders a backup (and a flash that keeps settings) holds. */
export function KeptFilesCard({ routerId, short }: Props) {
  const kept = useQuery({ queryKey: ['system-kept', routerId], queryFn: () => apiFetch<KeptFiles>(`/api/routers/${routerId}/system/kept-files`) })
  return (
    <section className="card stack" aria-labelledby="system-kept-h">
      <div className="hrow">
        <h2 id="system-kept-h">Files kept in a backup</h2>
        <Help topic={HELP.systemKept} />
      </div>
      <div className="muted">One path per line. A backup holds the config files changed since flashing, and these.</div>
      {kept.error && <div className="note x">{kept.error instanceof ApiError ? kept.error.detail : kept.error.message}</div>}
      {kept.data && <KeptForm routerId={routerId} short={short} kept={kept.data} />}
    </section>
  )
}
