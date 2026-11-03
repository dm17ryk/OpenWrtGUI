import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { apiFetch, downloadFile } from '../api/client'
import type { AuditEntry, RouterItem } from '../api/types'

function query(router: string, text: string, since: string): string {
  const params = new URLSearchParams()
  if (router) params.set('router', router)
  if (text) params.set('text', text)
  if (since) params.set('since', `${since}T00:00:00`)
  return `/api/audit?${params.toString()}`
}

export function AuditLog() {
  const [router, setRouter] = useState('')
  const [text, setText] = useState('')
  const [since, setSince] = useState('')
  const [exportError, setExportError] = useState<string | null>(null)
  const routers = useQuery({ queryKey: ['routers'], queryFn: () => apiFetch<RouterItem[]>('/api/routers') })
  const path = query(router, text, since)
  const entries = useQuery({ queryKey: ['audit', path], queryFn: () => apiFetch<AuditEntry[]>(path) })

  const exportAll = async (): Promise<void> => {
    setExportError(null)
    try {
      await downloadFile('/api/audit/export', 'openwrtgui-audit.zip')
    } catch (err) {
      setExportError(String(err))
    }
  }

  return (
    <main className="wrap">
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <div>
          <div className="eyebrow">Every command sent on your behalf · secrets masked</div>
          <h1>Audit log</h1>
        </div>
        <div className="spacer" />
        <button className="btn" type="button" onClick={() => void exportAll()}>
          Export for a bug report
        </button>
      </div>
      {exportError && <div className="note x">{exportError}</div>}
      <section className="card stack">
        <div className="grid">
          <div className="field">
            <label htmlFor="f-router">Router</label>
            <select id="f-router" className="in" value={router} onChange={(e) => setRouter(e.target.value)}>
              <option value="">All routers</option>
              {(routers.data ?? []).map((r) => (
                <option key={r.record.id} value={r.record.id}>
                  {r.record.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="f-text">Text</label>
            <input id="f-text" className="in" value={text} onChange={(e) => setText(e.target.value)} placeholder="command or screen" />
          </div>
          <div className="field">
            <label htmlFor="f-since">Since</label>
            <input id="f-since" className="in" type="date" value={since} onChange={(e) => setSince(e.target.value)} />
          </div>
        </div>
        <div className="scroll-x">
          <table className="tbl">
            <thead>
              <tr>
                <th>Time</th>
                <th>Router</th>
                <th>Screen</th>
                <th>Command</th>
                <th>Exit</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {(entries.data ?? []).map((e, i) => (
                <tr key={`${e.ts}-${i}`}>
                  <td className="mono" style={{ whiteSpace: 'nowrap' }}>
                    {new Date(e.ts).toLocaleString()}
                  </td>
                  <td>{e.router ?? '—'}</td>
                  <td>{e.screen}</td>
                  <td className="mono" style={{ overflowWrap: 'anywhere' }}>
                    {e.command}
                  </td>
                  <td className="mono">{e.exit_status ?? '—'}</td>
                  <td>{e.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {entries.data?.length === 0 && <div className="muted">Nothing matches.</div>}
      </section>
    </main>
  )
}
