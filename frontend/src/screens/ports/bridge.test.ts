import { expect, test } from 'vitest'
import { AP5_BRIDGE } from '../../testing/bridge'
import { bridgeDraft, bridgeRequest, newBridgeVlan, setCell } from './bridge'

test('the draft follows the router and asks nothing', () => {
  const rows = bridgeDraft(AP5_BRIDGE)
  expect(rows.map((r) => [r.vlan, r.local, r.cells.lan2])).toEqual([
    [1, true, 'u'],
    [10, true, '-'],
  ])
  expect(bridgeRequest(AP5_BRIDGE, rows)).toBeNull()
})

test('making a port untagged moves it out of the VLAN it was untagged in, as LuCI does', () => {
  const rows = [...bridgeDraft(AP5_BRIDGE), newBridgeVlan(AP5_BRIDGE, bridgeDraft(AP5_BRIDGE))]
  expect(rows[2].vlan).toBe(2)
  const moved = setCell(rows, rows[2].key, 'lan4', 'u')
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

test('the local switch and a delete', () => {
  const rows = bridgeDraft(AP5_BRIDGE).map((r) => (r.vlan === 10 ? { ...r, local: false } : r))
  expect(bridgeRequest(AP5_BRIDGE, rows)?.upserts).toEqual([{ section: 'cfg050f15', vlan: 10, members: { lan1: 't', lan4: 't' }, local: false }])
  const gone = bridgeDraft(AP5_BRIDGE).map((r) => (r.vlan === 10 ? { ...r, deleted: true } : r))
  expect(bridgeRequest(AP5_BRIDGE, gone)).toEqual({ upserts: [], deletes: ['cfg050f15'] })
})
