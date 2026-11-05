import { expect, test } from 'vitest'
import { AP2_NET } from '../../testing/net'
import { interfaceDraft, interfaceRequest } from './draft'

const lan = AP2_NET.interfaces[0]

test('a draft starts from the router and a request carries only the changed part', () => {
  const draft = interfaceDraft(lan, AP2_NET.devices)
  expect(draft).toEqual({ proto: 'static', address: '192.168.1.2/24', gateway: '', dns: [], mtu: '', ports: ['eth0.1'] })
  expect(interfaceRequest(lan, draft, AP2_NET.devices)).toBeNull()
  expect(interfaceRequest(lan, { ...draft, address: '192.168.1.12/24' }, AP2_NET.devices)).toEqual({
    name: 'lan',
    address: '192.168.1.12/24',
  })
})

test('the address goes as typed, so the router side refuses a bare one', () => {
  const draft = interfaceDraft(lan, AP2_NET.devices)
  expect(interfaceRequest(lan, { ...draft, address: '192.168.1.12' }, AP2_NET.devices)).toEqual({ name: 'lan', address: '192.168.1.12' })
})

test('gateway, DNS, MTU and bridge members', () => {
  const draft = interfaceDraft(lan, AP2_NET.devices)
  const changed = { ...draft, gateway: '192.168.1.1', dns: ['1.1.1.1'], mtu: '1400', ports: ['eth0.1', 'eth0.3'] }
  expect(interfaceRequest(lan, changed, AP2_NET.devices)).toEqual({
    name: 'lan',
    gateway: '192.168.1.1',
    dns: ['1.1.1.1'],
    mtu: 1400,
    bridge_ports: ['eth0.1', 'eth0.3'],
  })
})

test('a protocol change sends the protocol, and leaving static sends no address', () => {
  const wan = AP2_NET.interfaces[1]
  const draft = interfaceDraft(wan, AP2_NET.devices)
  expect(interfaceRequest(wan, { ...draft, proto: 'static', address: '10.0.0.2/24' }, AP2_NET.devices)).toEqual({
    name: 'wan',
    proto: 'static',
    address: '10.0.0.2/24',
  })
  expect(interfaceRequest(lan, { ...interfaceDraft(lan, AP2_NET.devices), proto: 'none' }, AP2_NET.devices)).toEqual({
    name: 'lan',
    proto: 'none',
  })
})
