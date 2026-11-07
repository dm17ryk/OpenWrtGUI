import type { BridgeView, LuciPageView, UciChange } from '../api/types'

function page(path: string, title: string, pkg: string, native: string | null, section: string, label?: string): LuciPageView {
  return { path, title, package: pkg, native, section, label: label ?? `${section} › ${title}` }
}

export const LUCI_PAGES: LuciPageView[] = [
  page('admin/network/dhcp', 'DHCP', 'luci-mod-network', null, 'Network'),
  page('admin/network/wireless', 'Wireless', 'luci-mod-network', 'wifi', 'Network'),
  page('admin/network/firewall/zones', 'General Settings', 'luci-app-firewall', 'firewall', 'Network › Firewall'),
  page('admin/status/iptables', 'Firewall', 'luci-mod-status', null, 'Status', 'Status › Firewall (iptables)'),
  page('admin/status/overview', 'Overview', 'luci-mod-status', 'dashboard', 'Status'),
]

export const DHCP_BRIDGE: BridgeView = {
  id: 'b1',
  router_id: 'ap2',
  page: LUCI_PAGES[0],
  url: 'http://127.0.0.1:50123/__owg/enter?k=secret&to=/cgi-bin/luci/admin/network/dhcp',
  access: 'write',
  opened_at: '2026-11-05T09:00:00',
}

export const LEASE_CHANGE: UciChange = { option: 'dhcp.lan.leasetime', before: '12h', after: '2h' }
