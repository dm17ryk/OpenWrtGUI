import type { InterfaceIn, InterfaceView, NetworkState } from '../../api/types'

type Devices = NetworkState['devices']

/** The hand-laid fields of one interface as the editor holds them (text as typed). */
export type InterfaceDraft = { proto: string; address: string; gateway: string; dns: string[]; mtu: string; ports: string[] }

function bridgeOf(v: InterfaceView, devices: Devices) {
  return devices.find((d) => d.name === v.conf?.device && d.type === 'bridge') ?? null
}

export function interfaceDraft(v: InterfaceView, devices: Devices): InterfaceDraft {
  const c = v.conf
  const address = c?.address ? `${c.address.ip}/${c.address.prefix}` : ''
  return {
    proto: c?.proto ?? 'none',
    address,
    gateway: c?.gateway ?? '',
    dns: c?.dns ?? [],
    mtu: c?.mtu != null ? String(c.mtu) : '',
    ports: bridgeOf(v, devices)?.ports ?? [],
  }
}

const same = (a: string[], b: string[]): boolean => a.length === b.length && a.every((x, i) => x === b[i])

/** Only the fields that differ from the router; null when nothing does. The address goes as typed. */
export function interfaceRequest(v: InterfaceView, d: InterfaceDraft, devices: Devices): InterfaceIn | null {
  if (!v.conf) return null
  const was = interfaceDraft(v, devices)
  const out: InterfaceIn = { name: v.conf.name }
  if (d.proto !== was.proto) out.proto = d.proto
  if (d.proto === 'static' && (d.address !== was.address || d.proto !== was.proto)) out.address = d.address
  if (d.gateway !== was.gateway) out.gateway = d.gateway
  if (!same(d.dns, was.dns)) out.dns = d.dns
  if (d.mtu !== was.mtu && d.mtu !== '') out.mtu = Number(d.mtu)
  if (bridgeOf(v, devices) && !same(d.ports, was.ports)) out.bridge_ports = d.ports
  return Object.keys(out).length > 1 ? out : null
}
