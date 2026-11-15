import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch } from '../../api/client'
import type { IptablesState } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

type Props = { routerId: string; short: string }

/** LuCI's Status › Firewall (iptables) view (v1.0a2 D6): the legacy rules per table, Reset counters, Restart firewall. */
export function IptablesTab({ routerId, short }: Props) {
  const client = useQueryClient()
  const base = `/api/routers/${routerId}/firewall/iptables`
  const state = useQuery({ queryKey: ['firewall-iptables', routerId], queryFn: () => apiFetch<IptablesState>(base), refetchInterval: 10_000 })
  const [picked, setPicked] = useState('iptables filter')
  const [hideEmpty, setHideEmpty] = useState(false)
  const [action, setAction] = useState<'reset' | 'restart' | null>(null)
  const run = usePlanApply(action ? `${base}/${action}` : base, action ? {} : null, () => {
    setAction(null)
    void client.invalidateQueries({ queryKey: ['firewall-iptables', routerId] })
  })
  const tables = state.data?.tables ?? []
  const table = tables.find((t) => `${t.program} ${t.table}` === picked) ?? tables[0]
  const chains = (table?.chains ?? []).filter((c) => !hideEmpty || c.rules.length > 0)
  return (
    <section className="card stack" aria-labelledby="fw-iptables-h">
      <div className="row">
        <div className="hrow">
          <h2 id="fw-iptables-h">Legacy iptables</h2>
          <Help topic={HELP.firewallIptables} />
        </div>
        <div className="spacer" />
        <label className="row">
          <input type="checkbox" checked={hideEmpty} onChange={(e) => setHideEmpty(e.target.checked)} />
          Hide empty chains
        </label>
        <button type="button" className="btn" onClick={() => setAction('reset')}>
          Reset counters
        </button>
        <button type="button" className="btn" onClick={() => setAction('restart')}>
          Restart firewall
        </button>
      </div>
      {state.error && <div className="note x">{state.error instanceof ApiError ? state.error.detail : state.error.message}</div>}
      {state.isPending && <div className="muted">Reading the rules…</div>}
      <div className="tabs" role="tablist" aria-label="iptables tables">
        {tables.map((t) => {
          const key = `${t.program} ${t.table}`
          return (
            <button key={key} type="button" role="tab" className={`tab${t === table ? ' on' : ''}`} aria-selected={t === table} onClick={() => setPicked(key)}>
              {t.program === 'ip6tables' ? `IPv6 ${t.table}` : t.table}
            </button>
          )
        })}
      </div>
      {table?.error && <div className="note x">{table.error}</div>}
      {chains.map((c) => (
        <div key={c.name} className="stack">
          <h3 className="mono">Chain {c.name}</h3>
          <div className="muted">{c.policy ? `Policy ${c.policy} · ${c.packets ?? 0} packets` : `${c.references ?? 0} references`}</div>
          {c.rules.length > 0 && (
            <div className="scroll-x">
              <table className="tbl" aria-label={`Chain ${c.name} rules`}>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Packets</th>
                    <th>Bytes</th>
                    <th>Target</th>
                    <th>Protocol</th>
                    <th>In</th>
                    <th>Out</th>
                    <th>Source</th>
                    <th>Destination</th>
                    <th>Options</th>
                  </tr>
                </thead>
                <tbody>
                  {c.rules.map((r) => (
                    <tr key={r.num}>
                      <td>{r.num}</td>
                      <td>{r.packets}</td>
                      <td>{r.bytes}</td>
                      <td className="mono">{r.target}</td>
                      <td className="mono">{r.prot}</td>
                      <td className="mono">{r.inp}</td>
                      <td className="mono">{r.out}</td>
                      <td className="mono">{r.source}</td>
                      <td className="mono">{r.destination}</td>
                      <td>
                        <span className="mono">{r.options}</span>
                        {r.comment && <div className="muted">{r.comment}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}
      <NetChange change={run} short={short} helpTopic={HELP.firewallIptables} show={action !== null} />
    </section>
  )
}
