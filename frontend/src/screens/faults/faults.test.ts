import { expect, test } from 'vitest'
import { PANEL } from '../../testing/faults'
import { EMPTY_DRAFT, type FaultDraft, faultRequest, untilText } from './faults'

const target = { mac: PANEL.mac, ip: PANEL.ip }
const draft = (patch: Partial<FaultDraft>): FaultDraft => ({ ...EMPTY_DRAFT, target, ...patch })

test('no request without a target, a fault, or a flow to block', () => {
  expect(faultRequest(EMPTY_DRAFT)).toBeNull()
  expect(faultRequest({ ...EMPTY_DRAFT, kind: 'isolate' })).toBeNull()
  expect(faultRequest(draft({ kind: null }))).toBeNull()
  expect(faultRequest(draft({ kind: 'block', flow: null }))).toBeNull()
})

test('block carries the flow and the loss; hold adds its seconds', () => {
  expect(faultRequest(draft({ kind: 'block', flow: 'rtp_in', loss: 30 }))).toEqual({ kind: 'block', target, flow: 'rtp_in', loss: 30, hold_s: null })
  expect(faultRequest(draft({ kind: 'block', flow: 'all_in', hold: true, hold_s: 60 }))).toEqual({ kind: 'block', target, flow: 'all_in', loss: 100, hold_s: 60 })
})

test('each kind sends only its own fields', () => {
  expect(faultRequest(draft({ kind: 'isolate' }))).toEqual({ kind: 'isolate', target, hold_s: null })
  expect(faultRequest(draft({ kind: 'link_down', port: 2 }))).toEqual({ kind: 'link_down', target, port: 2, hold_s: null })
  expect(faultRequest(draft({ kind: 'netem', netem: { ...EMPTY_DRAFT.netem, delay_ms: 120, jitter_ms: 30 } }))).toEqual({
    kind: 'netem',
    target,
    netem: { delay_ms: 120, jitter_ms: 30, distribution: 'uniform', loss_pct: 0, reorder_pct: 0, duplicate_pct: 0, direction: 'to' },
    hold_s: null,
  })
  // deauth is one shot and a ban ends in hostapd by itself: no hold
  expect(faultRequest(draft({ kind: 'deauth', hold: true, hold_s: 30 }))).toEqual({ kind: 'deauth', target })
  expect(faultRequest(draft({ kind: 'ban', ban_s: 60, hold: true }))).toEqual({ kind: 'ban', target, ban_s: 60 })
})

test('until reads as the time left on the router', () => {
  const now = new Date('2026-11-06T21:00:00Z')
  expect(untilText(null, now)).toBe('until cleared')
  expect(untilText('2026-11-06T21:00:42Z', now)).toBe('clears in 42 s')
  expect(untilText('2026-11-06T20:59:59Z', now)).toBe('clearing now')
})
