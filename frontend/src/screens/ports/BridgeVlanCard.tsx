import { useState } from 'react'
import type { BridgeState } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'
import { bridgeDraft, bridgeRequest, effectiveRows, newBridgeVlan, setCell, type BridgeRow } from './bridge'
import { CELL_TEXT, nextCell } from './vlan'

const MARK = { '-': '—', u: 'U', t: 'T' } as const

type Props = { routerId: string; short: string; state: BridgeState; onApplied: () => void }

/** LuCI's Switch/VLAN config on a DSA router (v1.0a3): one row per bridge VLAN, one column per port. */
export function BridgeVlanCard({ routerId, short, state, onApplied }: Props) {
  // null: the rows follow the router's state (so an Apply's refresh shows what the router has now)
  const [edited, setEdited] = useState<BridgeRow[] | null>(null)
  const rows = edited ?? bridgeDraft(state)
  const shown = effectiveRows(state, rows) // LuCI's untagged move, derived: clicking on through U undoes it
  const locked = !state.editable
  const body = locked ? null : bridgeRequest(state, shown)
  const change = usePlanApply(`/api/routers/${routerId}/ports/bridge`, body, () => {
    setEdited(null)
    onApplied()
  })
  const update = (key: string, patch: Partial<BridgeRow>): void => setEdited(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  const vlanOf = (row: BridgeRow) => state.vlans.find((x) => x.section === row.section)
  const usedBy = (row: BridgeRow): string => {
    const v = vlanOf(row)
    return v ? v.used_by.join(' · ') || '—' : 'new'
  }
  // what the router would refuse is greyed, with its reason as the title (v1.0a3 minor #67, v1.0c Task 13)
  const localLock = (row: BridgeRow): string | null => {
    const v = vlanOf(row)
    return v?.own && row.local ? `VLAN ${v.vlan} carries ${state.own_interface}, this app's connection: the router stays in it, so local stays on.` : null
  }
  const deleteLock = (row: BridgeRow): string | null => {
    const v = vlanOf(row)
    if (!v) return null
    const iface = v.used_by[0]
    if (iface) return `VLAN ${v.vlan} carries ${iface} (${state.bridge}.${v.vlan}). Move ${iface} to another device first.`
    return v.own ? `VLAN ${v.vlan} carries ${state.own_interface}, this app's connection.` : null
  }
  const carry = state.ports.filter((p) => p.may_carry).map((p) => p.name)
  return (
    <section className="card stack" aria-labelledby="bridge-h">
      <div className="row">
        <div className="hrow">
          <h2 id="bridge-h">VLANs · {state.bridge}</h2>
          <Help topic={HELP.portsBridge} />
        </div>
        <div className="spacer" />
        {!locked && (
          <button className="btn" type="button" onClick={() => setEdited([...rows, newBridgeVlan(state, rows)])}>
            + Add VLAN
          </button>
        )}
      </div>
      {state.blocker && <div className="note w">{state.blocker}</div>}
      {state.issues.length > 0 && (
        <ul className="note x">
          {state.issues.map((issue) => (
            <li key={issue}>{issue}</li>
          ))}
        </ul>
      )}
      <div className="scroll-x">
        <table className="tbl" aria-label="Bridge VLAN membership">
          <thead>
            <tr>
              <th>VLAN</th>
              {state.ports.map((p) => (
                <th key={p.name}>
                  {p.name}
                  {p.may_carry && (
                    <span className="muted" title="may carry this app's SSH">
                      {' '}
                      · SSH
                    </span>
                  )}
                </th>
              ))}
              <th>Local</th>
              <th>Used by</th>
              <th>
                <span className="sr-only">Delete</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => (
              <tr key={row.key} className={row.deleted ? 'muted' : undefined}>
                <td>
                  {row.section ? (
                    row.vlan
                  ) : (
                    <input className="in mono" style={{ width: 80 }} type="number" min={1} max={4094} aria-label="Number of new VLAN" value={row.vlan} onChange={(e) => update(row.key, { vlan: Number(e.target.value) })} />
                  )}
                </td>
                {state.ports.map((p) => {
                  const cell = row.cells[p.name] ?? '-'
                  return (
                    <td key={p.name}>
                      <button
                        className={`vcell ${cell === '-' ? '' : cell}`}
                        type="button"
                        disabled={locked || row.deleted}
                        aria-label={`VLAN ${row.vlan} ${p.name} ${CELL_TEXT[cell]}`}
                        onClick={() => setEdited(setCell(state, rows, row.key, p.name, nextCell(cell)))}
                      >
                        {MARK[cell]}
                      </button>
                    </td>
                  )
                })}
                <td>
                  <input
                    type="checkbox"
                    aria-label={`VLAN ${row.vlan} local`}
                    checked={row.local}
                    disabled={locked || row.deleted || localLock(row) !== null}
                    title={localLock(row) ?? undefined}
                    onChange={(e) => update(row.key, { local: e.target.checked })}
                  />
                </td>
                <td className="mono">{usedBy(row)}</td>
                <td>
                  {locked ? null : row.section ? (
                    <button
                      className="btn danger"
                      type="button"
                      aria-label={`Delete VLAN ${row.vlan}`}
                      aria-pressed={row.deleted}
                      disabled={!row.deleted && deleteLock(row) !== null}
                      title={row.deleted ? undefined : (deleteLock(row) ?? undefined)}
                      onClick={() => update(row.key, { deleted: !row.deleted })}
                    >
                      {row.deleted ? 'Keep' : 'Delete'}
                    </button>
                  ) : (
                    <button className="btn" type="button" aria-label={`Remove new VLAN ${row.vlan}`} onClick={() => setEdited(rows.filter((r) => r.key !== row.key))}>
                      Remove
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="muted">— not a member · U untagged (native) · T tagged. Making a port untagged in one VLAN takes it out of the VLAN it was untagged in. Local: the router itself is in the VLAN.</div>
      {carry.length > 0 && (
        <div className="muted">
          {carry.join(', ')} may carry this app&apos;s SSH: one of them keeps its VLAN {state.own_vlan} membership as it is.
        </div>
      )}
      {state.runtime.length > 0 && <div className="muted">Joined at run time, not edited here: {state.runtime.join(', ')}</div>}
      <NetChange change={change} short={short} helpTopic={HELP.portsBridge} show={body !== null} />
    </section>
  )
}
