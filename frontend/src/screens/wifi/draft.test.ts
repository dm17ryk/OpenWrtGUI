import { expect, test } from 'vitest'
import type { RadioState } from '../../api/types'
import { AP2_RADIO } from '../../testing/wifi'
import { channelSummary, draftFrom, modeSummary, requestFrom, widthText } from './draft'

test('summaries use the screen texts', () => {
  expect(modeSummary({ kind: 'auto', modes: [] })).toBe('Auto · router decides')
  expect(modeSummary({ kind: 'all', modes: [] })).toBe('All · b + g + n20 + n40')
  expect(modeSummary({ kind: 'set', modes: ['n20', 'b'] })).toBe('Only b + n20')
  expect(modeSummary({ kind: 'set', modes: [] })).toBe('nothing ticked')
  const allowed = AP2_RADIO.limits.channels
  expect(channelSummary({ kind: 'auto', channels: [] }, allowed)).toBe('Auto · any allowed channel')
  expect(channelSummary({ kind: 'all', channels: [] }, allowed)).toBe('All · 1–13')
  expect(channelSummary({ kind: 'none', channels: [] }, allowed)).toBe('None · radio parked')
  expect(channelSummary({ kind: 'set', channels: [6] }, allowed)).toBe('Fixed · ch 6')
  expect(channelSummary({ kind: 'set', channels: [11, 1, 6] }, allowed)).toBe('Pick among 1, 6, 11')
  expect(channelSummary({ kind: 'set', channels: [] }, allowed)).toBe('nothing ticked')
})

test('width follows the ticked modes', () => {
  expect(widthText({ kind: 'auto', modes: [] })).toBe('router default')
  expect(widthText({ kind: 'set', modes: ['n20', 'n40'] })).toBe('HT40 · 20 MHz fallback')
  expect(widthText({ kind: 'set', modes: ['n40'] })).toBe('HT40 · forced')
  expect(widthText({ kind: 'set', modes: ['b', 'n20'] })).toBe('HT20')
  expect(widthText({ kind: 'set', modes: ['g'] })).toBe('legacy 20 MHz')
})

test('an unchanged draft asks for nothing', () => {
  expect(requestFrom(AP2_RADIO, draftFrom(AP2_RADIO))).toBeNull()
})

test('only the changed parts are sent', () => {
  const d = draftFrom(AP2_RADIO)
  const req = requestFrom(AP2_RADIO, { ...d, modes: { kind: 'set', modes: ['n40'] }, channels: { kind: 'set', channels: [6] } })
  expect(req).toEqual({ radio: 'radio0', modes: { kind: 'set', modes: ['n40'] }, channels: { kind: 'set', channels: [6] } })
})

test('ssid changes and a typed key are sent; an empty key keeps the key', () => {
  const d = draftFrom(AP2_RADIO)
  const typed = { ...d, ssids: { default_radio0: { ssid: 'OpenWrt', security: 'wpa2' as const, key: 'new-lab-key' } } }
  expect(requestFrom(AP2_RADIO, typed)?.ssids).toEqual([{ section: 'default_radio0', key: 'new-lab-key' }])
  const renamed = { ...d, ssids: { default_radio0: { ssid: 'Lab', security: 'wpa3' as const, key: '' } } }
  expect(requestFrom(AP2_RADIO, renamed)?.ssids).toEqual([{ section: 'default_radio0', ssid: 'Lab', security: 'wpa3' }])
})

test('a missing TX mask is restored by sending the unchanged modes', () => {
  const pure: RadioState = { ...AP2_RADIO, up: true, modes: { kind: 'set', modes: ['n20'] }, mask: 'missing' }
  expect(requestFrom(pure, draftFrom(pure))).toEqual({ radio: 'radio0', modes: { kind: 'set', modes: ['n20'] } })
})

test('all four ticked reads as All', () => {
  const all: RadioState = { ...AP2_RADIO, modes: { kind: 'set', modes: ['b', 'g', 'n20', 'n40'] } }
  expect(draftFrom(all).modes.kind).toBe('all')
})
