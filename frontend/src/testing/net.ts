import type { InterfaceView, Lease, LiveTables, NetApplyResult, NetPlan, NetworkState, OptionRow } from '../api/types'

function live(name: string, up: boolean, proto: string, device: string | null, ipv4: { ip: string; prefix: number }[] = []) {
  return { name, up, proto, device, ipv4, ipv6: [], dynamic: false, parent: null, uptime_s: up ? 1786039 : null, errors: [] }
}

const LAN: InterfaceView = {
  conf: { name: 'lan', proto: 'static', device: 'br-lan', address: { ip: '192.168.1.2', prefix: 24 }, gateway: null, dns: [], mtu: null, auto: true },
  live: live('lan', true, 'static', 'br-lan', [{ ip: '192.168.1.2', prefix: 24 }]),
  own: true,
  dynamic_parent: null,
}

const WAN: InterfaceView = {
  conf: { name: 'wan', proto: 'dhcp', device: 'eth0.2', address: null, gateway: null, dns: [], mtu: null, auto: true },
  live: live('wan', false, 'dhcp', 'eth0.2'),
  own: false,
  dynamic_parent: null,
}

const LTE_4: InterfaceView = {
  conf: null,
  live: { ...live('lte_4', false, 'dhcp', 'wwan0'), dynamic: true, parent: 'lte' },
  own: false,
  dynamic_parent: 'lte',
}

/** AP2 as recorded 2026-11-05 (tests/fixtures/ap2/network.json), shortened. */
export const AP2_NET: NetworkState = {
  router_id: 'ap2',
  interfaces: [LAN, WAN, LTE_4],
  devices: [{ section: 'cfg030f15', name: 'br-lan', type: 'bridge', ports: ['eth0.1'] }],
  protocols: [
    { name: 'none', label: 'No address', options: 0 },
    { name: 'dhcp', label: 'DHCP client', options: 20 },
    { name: 'static', label: 'Static', options: 9 },
    { name: 'qmi', label: 'LTE (QMI)', options: 25 },
  ],
  own_interface: 'lan',
  pc_ip: '192.168.1.10',
  router_ip: '192.168.1.2',
  dhcp: [
    { section: 'lan', interface: 'lan', enabled: false, start: 100, limit: 150, leasetime: '12h', options: [], dhcpv6: 'disabled', ra: 'disabled' },
  ],
  hosts: [],
  dns: { section: 'cfg01411c', values: { domain: 'lan', local: '/lan/', rebind_protection: '1', cachesize: '1000' } },
  routes: [],
  rules: [],
}

const SESSION = '/var/run/rpcd/uci-<session>'

export const LAN_12_PLAN: NetPlan = {
  router_id: 'ap2',
  screen: 'Network',
  lines: [
    "ubus call session create '{\"timeout\":300}'",
    'set -e',
    `mkdir -p ${SESSION}`,
    `uci -P ${SESSION} set network.lan.ipaddr='192.168.1.12/24'`,
    "ubus call uci apply '{\"rollback\":true,\"timeout\":60,\"ubus_rpc_session\":\"<session>\"}'",
  ],
  warnings: [
    'Applies with a 60 s rollback: if the app cannot reach AP2 · office at 192.168.1.12 again and confirm, the router restores its previous network settings by itself.',
  ],
  rollback: true,
  target_host: '192.168.1.12',
  digest: 'c0ffee0123456789',
}

export const LAN_12_DONE: NetApplyResult = {
  router_id: 'ap2',
  applied: true,
  verified: true,
  checks: [
    { name: 'reconnected', ok: true, detail: 'AP2 · office answered at 192.168.1.12' },
    { name: 'confirmed', ok: true, detail: 'the router keeps the change' },
    { name: 'interface lan', ok: true, detail: 'up with 192.168.1.12/24' },
  ],
  error: null,
  host: '192.168.1.12',
}

/** AP2 with something in every card: two fixed addresses, a forwarder, a route and a rule (made up). */
export const AP2_NET_FULL: NetworkState = {
  ...AP2_NET,
  hosts: [
    { section: 'cfg0bfb35', name: 'bench-pc', macs: ['08:3a:88:5c:a8:39'], ip: '192.168.1.10', leasetime: null, gets_address: true },
    { section: 'cfg0cfb35', name: 'sta-1', macs: ['e4:5f:01:aa:bb:01'], ip: '192.168.1.50', leasetime: '1h', gets_address: true },
  ],
  dns: { section: 'cfg01411c', values: { domain: 'lan', local: '/lan/', rebind_protection: '1', cachesize: '1000', server: '1.1.1.1' } },
  routes: [
    { section: 'cfg0e1e2f', kind: 'route', interface: 'lan', target: '10.9.0.0/24', gateway: '192.168.1.1', metric: null, table: null, type: null, disabled: false },
  ],
  rules: [
    { section: 'cfg0f1e2f', kind: 'rule', src: '10.9.0.0/24', dest: null, in_iface: null, out_iface: null, lookup: 'main', priority: 100, action: null, disabled: false },
  ],
}

export const LEASES: Lease[] = [
  { family: 4, mac: '08:3a:88:5c:a8:39', ip: '192.168.1.10', hostname: 'bench-pc', expires_s: 40000 },
  { family: 4, mac: 'a4:83:e7:12:34:56', ip: '192.168.1.123', hostname: 'phone', expires_s: 3540 },
  { family: 6, mac: null, ip: 'fd12:3456::123', hostname: 'phone', expires_s: 3540 },
]

export const LIVE: LiveTables = {
  routes: [
    { family: 4, dst: 'default', gateway: '192.168.1.1', dev: 'br-lan', metric: null, proto: 'static', table: 'main', type: 'unicast' },
    { family: 4, dst: '192.168.1.0/24', gateway: null, dev: 'br-lan', metric: null, proto: 'kernel', table: 'main', type: 'unicast' },
    { family: 6, dst: 'fd12:3456::/64', gateway: null, dev: 'br-lan', metric: 1024, proto: 'static', table: 'main', type: 'unicast' },
  ],
  rules: [
    { family: 4, priority: 0, src: null, lookup: 'local' },
    { family: 4, priority: 32766, src: null, lookup: 'main' },
  ],
  raw: null,
}

function plan(lines: string[], warnings: string[] = [], rollback = false): NetPlan {
  return { router_id: 'ap2', screen: 'Network', lines, warnings, rollback, target_host: rollback ? '192.168.1.2' : null, digest: 'feed0123456789ab' }
}

export const DHCP_ON_PLAN = plan(
  ['set -e', 'uci delete dhcp.lan.ignore', 'uci commit dhcp', '/etc/init.d/dnsmasq reload'],
  ['AP1 · bench already serves DHCP on 192.168.1.0/24. Two DHCP servers on one subnet hand out clashing addresses; on the bench, AP1 is the only DHCP server.'],
)
export const HOSTS_PLAN = plan(['set -e', 'uci delete dhcp.cfg0cfb35', 'uci delete dhcp.cfg0bfb35', 'uci commit dhcp', '/etc/init.d/dnsmasq reload'])
export const DNS_PLAN = plan(['set -e', "uci delete dhcp.cfg01411c.server", "uci add_list dhcp.cfg01411c.server='1.1.1.1'", 'uci commit dhcp'])
export const ROUTE_PLAN = plan(
  ["ubus call session create '{\"timeout\":300}'", 'set -e', `uci -P ${SESSION} set network.$r1.target='10.8.0.0/24'`],
  ['Applies with a 60 s rollback: if the app cannot reach AP2 · office at 192.168.1.2 again and confirm, the router restores its previous network settings by itself.'],
  true,
)

export const LAN_OPTIONS: OptionRow[] = [
  { config: 'network', group: 'interface', section: 'lan', name: 'ipaddr', type: 'ip4addr', editor: 'text', value: '192.168.1.2/24', set_in_config: true, control: 'Address', writer: null },
  { config: 'network', group: 'interface', section: 'lan', name: 'ip6addr', type: 'ip6addr', editor: 'text', value: null, set_in_config: false, control: null, writer: null },
]
