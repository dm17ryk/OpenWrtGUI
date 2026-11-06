import type { NetPlan, PortView, PortsState } from '../api/types'

function port(num: number, label: string, link: boolean, extra: Partial<PortView> = {}): PortView {
  return {
    num,
    label,
    role: label === 'WAN' ? 'wan' : 'lan',
    link,
    speed_mbps: link ? 100 : null,
    full_duplex: link ? true : null,
    enabled: true,
    own: false,
    lock: null,
    ...extra,
  }
}

/** AP2's switch0 as the simulator shows it (tests/unit/net/test_ports.py): LAN1 = port 3 carries the PC. */
export const AP2_PORTS: PortsState = {
  router_id: 'ap2',
  switch: 'switch0',
  managed: true,
  ports: [
    port(3, 'LAN1', true, { own: true, lock: "carries this app's SSH" }),
    port(2, 'LAN2', false),
    port(1, 'LAN3', false),
    port(0, 'LAN4', false),
    port(4, 'WAN', false),
  ],
  vlans: [
    { section: 'cfg071ec7', vlan: 1, vid: null, members: { 0: 'u', 1: 'u', 2: 'u', 3: 'u', 6: 't' }, device: 'eth0.1', used_by: ['lan'] },
    { section: 'cfg081ec7', vlan: 2, vid: null, members: { 4: 'u', 6: 't' }, device: 'eth0.2', used_by: ['wan', 'wan6'] },
  ],
  mirror: { available: true, monitor: null, sources: {} },
  wifi_mirror: { present: false, running: null },
  can_disable: true,
  own_reason: 'only-link',
  cpu_port: 6,
  max_vlan: 15,
  own_interface: 'lan',
  port_count: 7,
}

export const UNMANAGED: PortsState = {
  ...AP2_PORTS,
  switch: null,
  managed: false,
  ports: [],
  vlans: [],
  mirror: { available: false, monitor: null, sources: {} },
  can_disable: false,
  own_reason: 'none',
  cpu_port: null,
  max_vlan: 0,
  port_count: 0,
}

function plan(lines: string[], warnings: string[] = [], rollback = false): NetPlan {
  return { router_id: 'ap2', screen: 'Ports', lines, warnings, rollback, target_host: rollback ? '192.168.1.2' : null, digest: 'beef0123456789ab' }
}

export const LAN2_OFF_PLAN = plan(['swconfig dev switch0 port 2 set enable 0'])

export const VLAN1_PLAN = plan(
  ["ubus call session create '{\"timeout\":300}'", 'set -e', "uci -P /var/run/rpcd/uci-<session> set network.cfg071ec7.ports='0t 1 2 3 6t'"],
  [
    "VLAN 1 carries lan, this app's connection; the change applies with a 60 s rollback.",
    'Applies with a 60 s rollback: if the app cannot reach AP2 · office at 192.168.1.2 again and confirm, the router restores its previous network settings by itself.',
  ],
  true,
)
