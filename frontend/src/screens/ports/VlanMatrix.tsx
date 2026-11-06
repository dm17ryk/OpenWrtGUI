import { useState } from 'react'
import type { PortsState } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'
import { CELL_TEXT, columns, newVlan, nextCell, vlanDraft, vlanRequest, type VlanRow } from './vlan'

const MARK = { '-': '—', u: 'U', t: 'T' } as const

type Props = { routerId: string; short: string; state: PortsState; onApplied: () => void }

/** VLAN membership: one row per VLAN, one column per socket (CPU last); a cell cycles — → U → T. */
export function VlanMatrix({ routerId, short, state, onApplied }: Props) {
  // null: the rows follow the router's state (so an Apply's refresh shows what the router has now)
  const [edited, setEdited] = useState<VlanRow[] | null>(null)
  const rows = edited ?? vlanDraft(state)
  const cols = columns(state)
  const body = vlanRequest(state, rows)
  const change = usePlanApply(`/api/routers/${routerId}/ports/vlans`, body, () => {
    setEdited(null)
    onApplied()
  })
  const update = (key: string, patch: Partial<VlanRow>): void => setEdited(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  const usedBy = (row: VlanRow): string => {
    const v = state.vlans.find((x) => x.section === row.section)
    return v ? [...v.used_by, v.device].filter(Boolean).join(' · ') : 'new'
  }
  return (
    <section className="card stack" aria-labelledby="vlans-h">
      <div className="row">
        <div className="hrow">
          <h2 id="vlans-h">VLANs</h2>
          <Help topic={HELP.portsVlans} />
        </div>
        <div className="spacer" />
        <button className="btn" type="button" onClick={() => setEdited([...rows, newVlan(state, rows)])}>
          + Add VLAN
        </button>
      </div>
      <div className="scroll-x">
        <table className="tbl" aria-label="VLAN membership">
          <thead>
            <tr>
              <th>VLAN</th>
              {cols.map((c) => (
                <th key={c.num}>
                  {c.label} · {c.num}
                </th>
              ))}
              <th>Used by</th>
              <th>
                <span className="sr-only">Delete</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} className={row.deleted ? 'muted' : undefined}>
                <td>
                  {row.section ? (
                    row.vlan
                  ) : (
                    <input
                      className="in mono"
                      style={{ width: 70 }}
                      type="number"
                      min={1}
                      max={state.max_vlan}
                      aria-label="Number of new VLAN"
                      value={row.vlan}
                      onChange={(e) => update(row.key, { vlan: Number(e.target.value) })}
                    />
                  )}
                </td>
                {cols.map((c) => {
                  const cell = row.cells[c.num] ?? '-'
                  return (
                    <td key={c.num}>
                      <button
                        className={`vcell ${cell === '-' ? '' : cell}`}
                        type="button"
                        disabled={row.deleted}
                        aria-label={`VLAN ${row.vlan} ${c.label} ${CELL_TEXT[cell]}`}
                        onClick={() => update(row.key, { cells: { ...row.cells, [c.num]: nextCell(cell) } })}
                      >
                        {MARK[cell]}
                      </button>
                    </td>
                  )
                })}
                <td className="mono">{usedBy(row)}</td>
                <td>
                  {row.section ? (
                    <button className="btn danger" type="button" aria-label={`Delete VLAN ${row.vlan}`} aria-pressed={row.deleted} onClick={() => update(row.key, { deleted: !row.deleted })}>
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
      <div className="muted">— not a member · U untagged · T tagged. A port is untagged in one VLAN at most.</div>
      <NetChange change={change} short={short} helpTopic={HELP.portsVlans} show={body !== null} />
    </section>
  )
}
