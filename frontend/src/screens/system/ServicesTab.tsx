import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch } from '../../api/client'
import type { ServiceAction, SystemServiceRow } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

const LABEL: Record<ServiceAction, string> = { start: 'Start', stop: 'Stop', restart: 'Restart', enable: 'Enable', disable: 'Disable' }

/** The actions a row offers: the app's own path restart only (D6), the rest what changes its state. */
function actions(s: SystemServiceRow): ServiceAction[] {
  if (s.protected) return ['restart']
  return [...(s.running ? (['stop', 'restart'] as const) : (['start'] as const)), s.enabled ? 'disable' : 'enable']
}

type Props = { routerId: string; routerName: string }

function ServicesCard({ routerId, routerName }: Props) {
  const short = routerName.split(' · ')[0] || routerId
  const client = useQueryClient()
  const rows = useQuery({ queryKey: ['system-services', routerId], queryFn: () => apiFetch<SystemServiceRow[]>(`/api/routers/${routerId}/system/services`) })
  const [pending, setPending] = useState<{ name: string; action: ServiceAction } | null>(null)
  const change = usePlanApply(`/api/routers/${routerId}/system/service`, pending, () => {
    setPending(null)
    void client.invalidateQueries({ queryKey: ['system-services', routerId] })
  })
  return (
    <section className="card stack" aria-labelledby="system-services-h">
      <div className="row">
        <div className="hrow">
          <h2 id="system-services-h">Services</h2>
          <Help topic={HELP.systemServices} />
        </div>
        <div className="spacer" />
        <button type="button" className="btn" onClick={() => void rows.refetch()}>
          Read again
        </button>
      </div>
      {rows.error && <div className="note x">{rows.error instanceof ApiError ? rows.error.detail : rows.error.message}</div>}
      {rows.isPending && <div className="muted">Reading the services…</div>}
      {rows.data && (
        <div className="scroll-x">
          <table className="tbl" aria-label="Services">
            <thead>
              <tr>
                <th>Service</th>
                <th>At boot</th>
                <th>Running</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.data.map((s) => (
                <tr key={s.name} className={pending?.name === s.name ? 'flag' : undefined}>
                  <td>
                    <span className="mono">{s.name}</span>
                    {s.protected && <div className="muted">{s.protected}</div>}
                  </td>
                  <td>{s.enabled ? 'enabled' : 'disabled'}</td>
                  <td>{s.running ? 'running' : 'not running'}</td>
                  <td>
                    <div className="row" style={{ gap: 6 }}>
                      {actions(s).map((a) => (
                        <button key={a} type="button" className="btn" aria-pressed={pending?.name === s.name && pending.action === a} onClick={() => setPending({ name: s.name, action: a })}>
                          {LABEL[a]}
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <NetChange change={change} short={short} helpTopic={HELP.systemServices} show={pending !== null} />
    </section>
  )
}

function RcLocalForm({ routerId, short, text }: { routerId: string; short: string; text: string }) {
  const [initial, setInitial] = useState(text)
  const [draft, setDraft] = useState(text)
  const body = draft !== initial ? { text: draft } : null
  const change = usePlanApply(`/api/routers/${routerId}/system/rc-local`, body, () => setInitial(draft))
  return (
    <>
      <label className="field">
        <span>rc.local</span>
        <textarea className="in mono" rows={10} spellCheck={false} value={draft} onChange={(e) => setDraft(e.target.value)} />
      </label>
      <NetChange change={change} short={short} helpTopic={HELP.systemRcLocal} show={body !== null} />
    </>
  )
}

function RcLocalCard({ routerId, routerName }: Props) {
  const short = routerName.split(' · ')[0] || routerId
  const file = useQuery({ queryKey: ['system-rc-local', routerId], queryFn: () => apiFetch<{ text: string }>(`/api/routers/${routerId}/system/rc-local`) })
  return (
    <section className="card stack" aria-labelledby="system-rclocal-h">
      <div className="hrow">
        <h2 id="system-rclocal-h">Startup script (rc.local)</h2>
        <Help topic={HELP.systemRcLocal} />
      </div>
      <div className="muted">Runs once at the end of every boot; its last line is exit 0.</div>
      {file.error && <div className="note x">{file.error instanceof ApiError ? file.error.detail : file.error.message}</div>}
      {file.data && file.data.text === '' && <div className="note">This router has no /etc/rc.local: Apply creates it.</div>}
      {file.data && <RcLocalForm routerId={routerId} short={short} text={file.data.text} />}
    </section>
  )
}

/** Every init script with its state and actions (D6), and the startup script (D7). */
export function ServicesTab(props: Props) {
  return (
    <>
      <ServicesCard {...props} />
      <RcLocalCard {...props} />
    </>
  )
}
