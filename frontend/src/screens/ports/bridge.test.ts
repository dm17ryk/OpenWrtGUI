import { expect, test } from 'vitest'
import { AP5_BRIDGE } from '../../testing/bridge'
import { bridgeDraft, bridgeRequest, effectiveRows, newBridgeVlan, setCell, type BridgeRow } from './bridge'

const shown = (rows: BridgeRow[]): BridgeRow[] => effectiveRows(AP5_BRIDGE, rows)
const click = (rows: BridgeRow[], key: string, port: string, cell: 'u' | 't' | '-'): BridgeRow[] => setCell(AP5_BRIDGE, rows, key, port, cell)

test('the draft follows the router and asks nothing', () => {
  const rows = bridgeDraft(AP5_BRIDGE)
  expect(rows.map((r) => [r.vlan, r.local, r.cells.lan2])).toEqual([
    [1, true, 'u'],
    [10, true, '-'],
  ])
  expect(bridgeRequest(AP5_BRIDGE, shown(rows))).toBeNull()
})

test('making a port untagged moves it out of the VLAN it was untagged in, as LuCI does', () => {
  const rows = [...bridgeDraft(AP5_BRIDGE), newBridgeVlan(AP5_BRIDGE, bridgeDraft(AP5_BRIDGE))]
  expect(rows[2].vlan).toBe(2)
  const moved = shown(click(rows, rows[2].key, 'lan4', 'u'))
  expect(moved[0].cells.lan4).toBe('-') // it was untagged in VLAN 1
  expect(moved[1].cells.lan4).toBe('t') // tagged in VLAN 10: LuCI's move keeps tagged memberships
  expect(bridgeRequest(AP5_BRIDGE, moved)).toEqual({
    upserts: [
      { section: 'cfg040f15', vlan: 1, members: { lan1: 'u', lan2: 'u', lan3: 'u' }, local: true },
      { vlan: 2, members: { lan4: 'u' }, local: true },
    ],
    deletes: [],
  })
})

test('passing through U on the way to T leaves the native VLAN as it was (review Important 1)', () => {
  const rows = bridgeDraft(AP5_BRIDGE)
  const throughU = click(rows, 'cfg050f15', 'lan2', 'u')
  expect(shown(throughU)[0].cells.lan2).toBe('-') // while VLAN 10 is U for lan2, VLAN 1 is not
  const tagged = click(throughU, 'cfg050f15', 'lan2', 't')
  expect(shown(tagged)[0].cells.lan2).toBe('u') // back in VLAN 1 untagged
  expect(bridgeRequest(AP5_BRIDGE, shown(tagged))).toEqual({
    upserts: [{ section: 'cfg050f15', vlan: 10, members: { lan1: 't', lan2: 't', lan4: 't' }, local: true }],
    deletes: [],
  })
})

test('clicking the hidden native cell takes the port back, and the other VLAN lets it go', () => {
  const throughU = click(bridgeDraft(AP5_BRIDGE), 'cfg050f15', 'lan2', 'u')
  const back = shown(click(throughU, 'cfg040f15', 'lan2', 'u'))
  expect(back[0].cells.lan2).toBe('u')
  expect(back[1].cells.lan2).toBe('-')
  expect(bridgeRequest(AP5_BRIDGE, back)).toBeNull()
})

test('the local switch and a delete', () => {
  const rows = bridgeDraft(AP5_BRIDGE).map((r) => (r.vlan === 10 ? { ...r, local: false } : r))
  expect(bridgeRequest(AP5_BRIDGE, shown(rows))?.upserts).toEqual([{ section: 'cfg050f15', vlan: 10, members: { lan1: 't', lan4: 't' }, local: false }])
  const gone = bridgeDraft(AP5_BRIDGE).map((r) => (r.vlan === 10 ? { ...r, deleted: true } : r))
  expect(bridgeRequest(AP5_BRIDGE, shown(gone))).toEqual({ upserts: [], deletes: ['cfg050f15'] })
})
