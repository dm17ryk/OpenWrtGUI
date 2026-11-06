import type { PortsState, VlanIn, VlansIn } from '../../api/types'

/** A port in a VLAN: not a member, untagged or tagged. */
export type Cell = '-' | 'u' | 't'
export type Column = { num: number; label: string }
export type VlanRow = { key: string; section: string | null; vlan: number; cells: Record<number, Cell>; deleted: boolean }

const NEXT: Record<Cell, Cell> = { '-': 'u', u: 't', t: '-' }

export const nextCell = (c: Cell): Cell => NEXT[c]

export const CELL_TEXT: Record<Cell, string> = { '-': 'not a member', u: 'untagged', t: 'tagged' }

/** The matrix columns: the sockets in label order (as the front panel), the CPU port last. */
export function columns(state: PortsState): Column[] {
  const sockets = state.ports.map((p) => ({ num: p.num, label: p.label }))
  return state.cpu_port === null ? sockets : [...sockets, { num: state.cpu_port, label: 'CPU' }]
}

function members(cells: Record<number, Cell>): VlanIn['members'] {
  return Object.fromEntries(Object.entries(cells).filter(([, c]) => c !== '-')) as VlanIn['members']
}

const sameMembers = (a: VlanIn['members'], b: VlanIn['members']): boolean =>
  JSON.stringify(Object.entries(a).sort()) === JSON.stringify(Object.entries(b).sort())

/** One row per VLAN; ports that are not columns (none on a usual switch) keep their membership. */
export function vlanDraft(state: PortsState): VlanRow[] {
  const empty = Object.fromEntries(columns(state).map((c) => [c.num, '-' as Cell]))
  return state.vlans.map((v) => ({ key: v.section, section: v.section, vlan: v.vlan, cells: { ...empty, ...v.members }, deleted: false }))
}

/** A new VLAN with the lowest number no row uses, tagged on the CPU port so the router can reach it. */
export function newVlan(state: PortsState, rows: VlanRow[]): VlanRow {
  const used = new Set(rows.map((r) => r.vlan))
  let vlan = 1
  while (used.has(vlan) && vlan < state.max_vlan) vlan += 1
  const cells: Record<number, Cell> = Object.fromEntries(columns(state).map((c) => [c.num, c.num === state.cpu_port ? 't' : '-']))
  return { key: `new-${rows.length}-${vlan}`, section: null, vlan, cells, deleted: false }
}

/** The changed VLANs (each with its whole member list) and the deleted ones; null when nothing changed. */
export function vlanRequest(state: PortsState, rows: VlanRow[]): VlansIn | null {
  const upserts: VlanIn[] = []
  const deletes: string[] = []
  for (const row of rows) {
    if (row.deleted) {
      if (row.section) deletes.push(row.section)
      continue
    }
    const old = state.vlans.find((v) => v.section === row.section)
    const now = members(row.cells)
    if (old && old.vlan === row.vlan && sameMembers(old.members, now)) continue
    upserts.push({ ...(row.section ? { section: row.section } : {}), vlan: row.vlan, members: now })
  }
  return upserts.length || deletes.length ? { upserts, deletes } : null
}
