import { useState } from 'react'
import { Link } from 'react-router'
import type { InterfaceIn, InterfaceView, NetApplyResult, NetworkState } from '../../api/types'
import { CheckList } from '../../components/CheckList'
import { PreviewApply } from '../../components/PreviewApply'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { InterfaceEditor } from './InterfaceEditor'
import { RollbackWait } from './NetChange'
import { uptimeText } from './rows'

type Props = { routerId: string; routerName: string; host: string; state: NetworkState; onApplied: () => void }

const nameOf = (v: InterfaceView): string => v.conf?.name ?? v.live?.name ?? ''

function address(v: InterfaceView): string {
  const a = v.conf?.address ?? v.live?.ipv4[0]
  return a ? `${a.ip}/${a.prefix}` : '—'
}

// net/interfaces.py: a new interface still needs a firewall zone, which the Firewall screen sets
const ZONE_NOTE = /^Put (\S+) in a firewall zone on the Firewall screen \(Zones\)\.$/

function NewInterface({ routerId, routerName, state, onApplied }: { routerId: string; routerName: string; state: NetworkState; onApplied: (r: NetApplyResult) => void }) {
  const [draft, setDraft] = useState({ name: '', proto: 'static', device: '', address: '' })
  const body: InterfaceIn | null = draft.name
    ? {
        name: draft.name,
        create: true,
        proto: draft.proto,
        ...(draft.device ? { device: draft.device } : {}),
        ...(draft.proto === 'static' ? { address: draft.address } : {}),
      }
    : null
  const change = usePlanApply(`/api/routers/${routerId}/network/interfaces`, body, onApplied)
  const warnings = body ? (change.plan?.warnings ?? []) : []
  const zoneNote = warnings.map((w) => ZONE_NOTE.exec(w)?.[1]).find(Boolean)
  return (
    <div className="card stack" aria-label="New interface">
      <div className="grid">
        <label className="field">
          <span>Name</span>
          <input className="in mono" aria-label="New interface name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        </label>
        <label className="field">
          <span>Protocol</span>
          <select className="in" aria-label="New interface protocol" value={draft.proto} onChange={(e) => setDraft({ ...draft, proto: e.target.value })}>
            {state.protocols.map((p) => (
              <option key={p.name} value={p.name}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Device</span>
          <input className="in mono" aria-label="New interface device" placeholder="eth0.3" value={draft.device} onChange={(e) => setDraft({ ...draft, device: e.target.value })} />
        </label>
        {draft.proto === 'static' && (
          <label className="field">
            <span>Address</span>
            <input className="in mono" aria-label="New interface address" placeholder="10.3.0.1/24" value={draft.address} onChange={(e) => setDraft({ ...draft, address: e.target.value })} />
          </label>
        )}
      </div>
      {zoneNote && (
        <div className="note w">
          Put {zoneNote} in a firewall zone on the <Link to={`/routers/${routerId}/firewall?tab=zones`}>Firewall screen (Zones)</Link>.
        </div>
      )}
      {body && (
        <PreviewApply
          heading="Commands that will run"
          lines={change.plan?.lines ?? []}
          warnings={warnings.filter((w) => !ZONE_NOTE.test(w))}
          error={change.error}
          isBusy={change.isBusy}
          applyLabel="Add with rollback"
          onApply={() => void change.apply()}
          helpTopic={HELP.netRollback}
        />
      )}
      {body && change.isBusy && <RollbackWait router={routerName} target={change.plan?.target_host ?? null} />}
      {change.result && <CheckList result={change.result} provenText="Applied and confirmed" />}
    </div>
  )
}

/** Router addresses: every interface, its protocol, address and state; Edit opens one. */
export function Interfaces({ routerId, routerName, host, state, onApplied }: Props) {
  const [editing, setEditing] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const label = (proto: string): string => state.protocols.find((p) => p.name === proto)?.label ?? proto
  const open = state.interfaces.find((v) => v.conf?.name === editing) ?? null
  return (
    <section className="card stack" aria-labelledby="ifaces-h">
      <div className="row">
        <div className="hrow">
          <h2 id="ifaces-h">Router addresses</h2>
          <Help topic={HELP.netAddresses} />
        </div>
        <div className="spacer" />
        <button className="btn" type="button" aria-expanded={adding} onClick={() => setAdding(!adding)}>
          + Interface
        </button>
      </div>
      <div className="scroll-x">
        <table className="tbl" aria-label="Router addresses">
          <thead>
            <tr>
              <th>Interface</th>
              <th>Protocol</th>
              <th>Address</th>
              <th>Gateway / DNS</th>
              <th>State</th>
              <th>
                <span className="sr-only">Edit</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {state.interfaces.map((v) => {
              const name = nameOf(v)
              const proto = v.conf?.proto ?? v.live?.proto ?? ''
              const extra = [v.conf?.gateway, ...(v.conf?.dns ?? [])].filter(Boolean).join(' · ')
              return (
                <tr key={name}>
                  <td>
                    <span className="mono">{name}</span> {v.own && <span className="b air">this app's connection</span>}
                  </td>
                  <td>{label(proto)}</td>
                  <td className="mono">{address(v)}</td>
                  <td className="mono">{extra || '—'}</td>
                  <td>
                    {v.dynamic_parent ? (
                      <span className="muted">made by {v.dynamic_parent} at run time</span>
                    ) : (
                      <span className={v.live?.up ? 'b air' : 'b park'}>
                        {v.live?.up ? (v.live.uptime_s != null ? `up · ${uptimeText(v.live.uptime_s)}` : 'up') : 'down'}
                      </span>
                    )}
                  </td>
                  <td>
                    {v.conf?.proto === 'qmi' && (
                      <Link className="btn" to={`/routers/${routerId}/lte`}>
                        LTE screen
                      </Link>
                    )}{' '}
                    {v.conf && (
                      <button className="btn" type="button" aria-label={`Edit ${name}`} aria-expanded={editing === name} onClick={() => setEditing(editing === name ? null : name)}>
                        Edit
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {adding && <NewInterface routerId={routerId} routerName={routerName} state={state} onApplied={onApplied} />}
      {open && <InterfaceEditor key={editing} routerId={routerId} routerName={routerName} host={host} view={open} state={state} onApplied={onApplied} />}
    </section>
  )
}
