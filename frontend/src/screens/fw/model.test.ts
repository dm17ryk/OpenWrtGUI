import { expect, test } from 'vitest'
import type { RuleView } from '../../api/types'
import { AP1_FW } from '../../testing/fw'
import { cellsOf, effectIn, modelRequest, needsPins } from './model'

const ping = AP1_FW.rules.find((r) => r.conf.name === 'Allow-Ping') as RuleView
const panelPing = AP1_FW.rules.find((r) => r.conf.name === 'Block-panel-ping') as RuleView

test('cells are the zones’ policies per direction', () => {
  expect(cellsOf(AP1_FW)).toEqual({
    'lan.input': 'ACCEPT',
    'lan.forward': 'ACCEPT',
    'lan.output': 'ACCEPT',
    'wan.input': 'REJECT',
    'wan.forward': 'REJECT',
    'wan.output': 'ACCEPT',
  })
})

test('effectIn flips with the cell', () => {
  const cells = cellsOf(AP1_FW)
  expect(effectIn(ping, cells)).toBe('allows')
  expect(effectIn(ping, { ...cells, 'wan.input': 'ACCEPT' })).toBe('no-effect-allow')
  expect(effectIn(panelPing, cells)).toBe('blocks')
  expect(effectIn(panelPing, { ...cells, 'lan.input': 'DROP' })).toBe('no-effect-block')
})

test('a forward rule that meets a forwarding keeps the router’s effect', () => {
  const forward: RuleView = { ...ping, direction: 'forward', zone: 'lan', conf: { ...ping.conf, src: 'lan', dest: 'wan' }, effect: 'no-effect-allow' }
  const cells = { ...cellsOf(AP1_FW), 'lan.forward': 'REJECT' as const }
  expect(effectIn(forward, cells, AP1_FW.conf.forwardings)).toBe('no-effect-allow')
  // without the forwarding the cell decides
  expect(effectIn(forward, cells, [])).toBe('allows')
})

test('a disabled rule or one without a zone keeps its effect', () => {
  expect(effectIn({ ...ping, conf: { ...ping.conf, enabled: false }, effect: 'other' }, { 'wan.input': 'ACCEPT' })).toBe('other')
  expect(effectIn({ ...ping, direction: null, zone: null, effect: 'other' }, {})).toBe('other')
})

test('the request carries only the changed cells, and null when nothing changed', () => {
  const cells = cellsOf(AP1_FW)
  expect(modelRequest(AP1_FW, cells, new Set())).toBeNull()
  expect(modelRequest(AP1_FW, { ...cells, 'wan.input': 'ACCEPT' }, new Set())).toEqual({ cells: { 'wan.input': 'ACCEPT' }, pins_removed: [] })
})

test('removed pins are sent while the own zone blocks, in pin order', () => {
  const blocked = { ...cellsOf(AP1_FW), 'lan.input': 'REJECT' as const }
  expect(needsPins(AP1_FW, blocked)).toBe(true)
  expect(modelRequest(AP1_FW, blocked, new Set(['dhcpdns', 'ssh']))).toEqual({ cells: { 'lan.input': 'REJECT' }, pins_removed: ['ssh', 'dhcpdns'] })
  // back on Allow all the pins stay: nothing removed is sent
  expect(needsPins(AP1_FW, cellsOf(AP1_FW))).toBe(false)
  expect(modelRequest(AP1_FW, { ...cellsOf(AP1_FW), 'wan.output': 'DROP' }, new Set(['ssh']))).toEqual({ cells: { 'wan.output': 'DROP' }, pins_removed: [] })
})
