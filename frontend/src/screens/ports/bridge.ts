import type { BridgeState, BridgeVlanIn, BridgeVlansIn } from '../../api/types'
import type { Cell } from './vlan'

/** One VLAN of the bridge as the card edits it (v1.0a3): a cell per port, the local switch. */
export type BridgeRow = { key: string; section: string | null; vlan: number; local: boolean; cells: Record<string, Cell>; deleted: boolean }

const MAX_VLAN = 4094

function emptyCells(state: BridgeState): Record<string, Cell> {
  return Object.fromEntries(state.ports.map((p) => [p.name, '-' as Cell]))
}

export function bridgeDraft(state: BridgeState): BridgeRow[] {
  return state.vlans.map((v) => ({ key: v.section, section: v.section, vlan: v.vlan, local: v.local, cells: { ...emptyCells(state), ...v.members }, deleted: false }))
}

/** LuCI's move: a port made untagged in one VLAN leaves the VLAN it was untagged in; tagged memberships stay. */
export function setCell(rows: BridgeRow[], key: string, port: string, cell: Cell): BridgeRow[] {
  return rows.map((r) => {
    if (r.key === key) return { ...r, cells: { ...r.cells, [port]: cell } }
    if (cell === 'u' && !r.deleted && r.cells[port] === 'u') return { ...r, cells: { ...r.cells, [port]: '-' } }
    return r
  })
}

/** A new VLAN with the lowest number no row uses, local on, no ports yet. */
export function newBridgeVlan(state: BridgeState, rows: BridgeRow[]): BridgeRow {
  const used = new Set(rows.map((r) => r.vlan))
  let vlan = 1
  while (used.has(vlan) && vlan < MAX_VLAN) vlan += 1
  return { key: `new-${rows.length}-${vlan}`, section: null, vlan, local: true, cells: emptyCells(state), deleted: false }
}

function members(cells: Record<string, Cell>): BridgeVlanIn['members'] {
  return Object.fromEntries(Object.entries(cells).filter(([, c]) => c !== '-')) as BridgeVlanIn['members']
}

const same = (a: BridgeVlanIn['members'], b: BridgeVlanIn['members']): boolean => JSON.stringify(Object.entries(a).sort()) === JSON.stringify(Object.entries(b).sort())

/** The changed VLANs, each with its whole member list, and the deleted ones; null when nothing changed. */
export function bridgeRequest(state: BridgeState, rows: BridgeRow[]): BridgeVlansIn | null {
  const upserts: BridgeVlanIn[] = []
  const deletes: string[] = []
  for (const row of rows) {
    if (row.deleted) {
      if (row.section) deletes.push(row.section)
      continue
    }
    const old = state.vlans.find((v) => v.section === row.section)
    const now = members(row.cells)
    if (old && old.local === row.local && same(old.members, now)) continue
    upserts.push({ ...(row.section ? { section: row.section } : {}), vlan: row.vlan, members: now, local: row.local })
  }
  return upserts.length || deletes.length ? { upserts, deletes } : null
}
