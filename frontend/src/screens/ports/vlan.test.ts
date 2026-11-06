import { expect, test } from 'vitest'
import { AP2_PORTS } from '../../testing/ports'
import { columns, newVlan, nextCell, vlanDraft, vlanRequest } from './vlan'

test('a cell cycles not a member → untagged → tagged → not a member', () => {
  expect(nextCell('-')).toBe('u')
  expect(nextCell('u')).toBe('t')
  expect(nextCell('t')).toBe('-')
})

test('the columns are the sockets in label order, the CPU last', () => {
  expect(columns(AP2_PORTS).map((c) => `${c.label} · ${c.num}`)).toEqual(['LAN1 · 3', 'LAN2 · 2', 'LAN3 · 1', 'LAN4 · 0', 'WAN · 4', 'CPU · 6'])
})

test('nothing changed sends nothing', () => {
  expect(vlanRequest(AP2_PORTS, vlanDraft(AP2_PORTS))).toBeNull()
})

test('only the changed VLAN is sent, with its whole member list', () => {
  const rows = vlanDraft(AP2_PORTS).map((r) => (r.vlan === 1 ? { ...r, cells: { ...r.cells, 0: nextCell(r.cells[0]) } } : r))
  expect(vlanRequest(AP2_PORTS, rows)).toEqual({
    upserts: [{ section: 'cfg071ec7', vlan: 1, members: { 0: 't', 1: 'u', 2: 'u', 3: 'u', 6: 't' } }],
    deletes: [],
  })
})

test('a new VLAN goes without a section, a deleted one by its section', () => {
  const rows = vlanDraft(AP2_PORTS).map((r) => (r.vlan === 2 ? { ...r, deleted: true } : r))
  const added = newVlan(AP2_PORTS, rows)
  expect(added.vlan).toBe(3)
  expect(added.cells[6]).toBe('t')
  const withPort = { ...added, cells: { ...added.cells, 2: 't' as const } }
  expect(vlanRequest(AP2_PORTS, [...rows, withPort])).toEqual({
    upserts: [{ vlan: 3, members: { 2: 't', 6: 't' } }],
    deletes: ['cfg081ec7'],
  })
})
