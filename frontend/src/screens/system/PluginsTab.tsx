import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { ApiError, apiFetch } from '../../api/client'
import type { PluginState } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { luciPageLink } from '../luci/pages'
import { NetChange } from '../net/NetChange'

type Props = { routerId: string; routerName: string }
type Change = { enabled?: boolean; groups: Record<string, boolean>; plugins: Record<string, boolean>; remove: string[] }
const NONE: Change = { groups: {}, plugins: {}, remove: [] }

const isEmpty = (c: Change): boolean =>
  c.enabled === undefined && Object.keys(c.groups).length === 0 && Object.keys(c.plugins).length === 0 && c.remove.length === 0

/** LuCI's System › Plugins (v1.0a2 D4): the global switch, each group's and each plugin's; options in LuCI. */
export function PluginsTab({ routerId, routerName }: Props) {
  const short = routerName.split(' · ')[0] || routerId
  const client = useQueryClient()
  const state = useQuery({ queryKey: ['system-plugins', routerId], queryFn: () => apiFetch<PluginState>(`/api/routers/${routerId}/system/plugins`) })
  const [change, setChange] = useState<Change>(NONE)
  const plan = usePlanApply(`/api/routers/${routerId}/system/plugins`, isEmpty(change) ? null : change, () => {
    setChange(NONE)
    void client.invalidateQueries({ queryKey: ['system-plugins', routerId] })
  })
  const data = state.data
  return (
    <section className="card stack" aria-labelledby="system-plugins-h">
      <div className="row">
        <div className="hrow">
          <h2 id="system-plugins-h">Plugins</h2>
          <Help topic={HELP.systemPlugins} />
        </div>
        <div className="spacer" />
        <Link className="btn" to={luciPageLink(routerId, 'admin/system/plugins')}>
          Configure in LuCI
        </Link>
      </div>
      {state.error && <div className="note x">{state.error instanceof ApiError ? state.error.detail : state.error.message}</div>}
      {state.isPending && <div className="muted">Reading the plugins…</div>}
      {data && data.missing.length > 0 && <div className="note">{short} has no /etc/config/luci_plugins: LuCI&apos;s Plugins page is not on this image.</div>}
      {data && data.missing.length === 0 && (
        <>
          <label className="row">
            <input type="checkbox" checked={change.enabled ?? data.enabled} onChange={(e) => setChange({ ...change, enabled: e.target.checked })} />
            Plugins on
          </label>
          {data.groups.map((g) => (
            <label key={g.key} className="row">
              <input
                type="checkbox"
                checked={change.groups[g.key] ?? g.enabled}
                onChange={(e) => setChange({ ...change, groups: { ...change.groups, [g.key]: e.target.checked } })}
              />
              <span className="mono">{g.key}</span> plugins on
            </label>
          ))}
          {data.plugins.length === 0 && <div className="muted">No plugins are installed on {short}.</div>}
          {data.plugins.length > 0 && (
            <div className="scroll-x">
              <table className="tbl" aria-label="Plugins">
                <thead>
                  <tr>
                    <th>On</th>
                    <th>Plugin</th>
                    <th>Group</th>
                    <th>Options</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.plugins.map((p) => (
                    <tr key={p.id}>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`${p.name} on`}
                          disabled={!p.installed}
                          checked={change.plugins[p.id] ?? p.enabled}
                          onChange={(e) => setChange({ ...change, plugins: { ...change.plugins, [p.id]: e.target.checked } })}
                        />
                      </td>
                      <td>
                        <strong>{p.title || p.name}</strong>
                        {p.description && <div className="muted">{p.description}</div>}
                        {!p.installed && <div className="note w">Missing plugin: its file is gone</div>}
                      </td>
                      <td className="mono">{p.group}</td>
                      <td className="mono">{Object.entries(p.options).map(([k, v]) => `${k}=${v}`).join(' ') || '—'}</td>
                      <td>
                        {!p.installed && p.configured && (
                          <button type="button" className="btn" disabled={change.remove.includes(p.id)} onClick={() => setChange({ ...change, remove: [...change.remove, p.id] })}>
                            Remove
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <NetChange change={plan} short={short} helpTopic={HELP.systemPlugins} show={!isEmpty(change)} />
        </>
      )}
    </section>
  )
}
