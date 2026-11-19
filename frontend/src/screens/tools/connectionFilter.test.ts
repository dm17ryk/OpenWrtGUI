import { expect, test } from 'vitest'
import type { Connection } from '../../api/types'
import { type ConnectionFilter, byProtocol, matches } from './connectionFilter'

const SIP: Connection = { proto: 'udp', src: '10.0.0.5', dst: '10.0.0.9', sport: 5060, dport: 5060, state: null, bytes: 8100, helper: 'sip' }
const SSH: Connection = { proto: 'tcp', src: '10.0.0.7', dst: '192.168.1.2', sport: 53498, dport: 22, state: 'ESTABLISHED', bytes: 10000, helper: null }
const PING: Connection = { proto: 'icmp', src: '10.0.0.7', dst: '10.0.0.1', sport: null, dport: null, state: null, bytes: 168 }
const GRE: Connection = { proto: 'gre', src: '10.0.0.7', dst: '10.1.1.1', sport: null, dport: null, state: null, bytes: 50 }

const ALL: ConnectionFilter = { text: '', proto: 'all', sipOnly: false }

test('text matches an address or a port, in part', () => {
  expect(matches(SIP, { ...ALL, text: '5060' })).toBe(true)
  expect(matches(SSH, { ...ALL, text: '5060' })).toBe(false)
  expect(matches(SSH, { ...ALL, text: '192.168' })).toBe(true)
  expect(matches(PING, { ...ALL, text: ' 10.0.0.1 ' })).toBe(true) // spaces around it do not count
})

test('protocol, with Other for anything but TCP, UDP and ICMP', () => {
  expect([SIP, SSH, PING, GRE].filter((c) => matches(c, { ...ALL, proto: 'other' }))).toEqual([GRE])
  expect([SIP, SSH, PING, GRE].filter((c) => matches(c, { ...ALL, proto: 'tcp' }))).toEqual([SSH])
  expect(matches({ ...SSH, proto: 'TCP' }, { ...ALL, proto: 'tcp' })).toBe(true)
})

test('SIP only keeps what the SIP helper handles', () => {
  expect([SIP, SSH, PING].filter((c) => matches(c, { ...ALL, sipOnly: true }))).toEqual([SIP])
})

test('counts by protocol', () => {
  expect(byProtocol([SIP, SSH, PING, GRE, SSH])).toEqual([
    ['tcp', 2],
    ['gre', 1],
    ['icmp', 1],
    ['udp', 1],
  ])
})
