import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '../../api/client'
import type { LuciPageView } from '../../api/types'

/** The router's LuCI pages, read once per minute at most (the menu only changes with new packages). */
export function useLuciPages(routerId: string) {
  return useQuery({
    queryKey: ['luci-pages', routerId],
    queryFn: () => apiFetch<LuciPageView[]>(`/api/routers/${routerId}/luci/pages`),
    retry: false,
    staleTime: 60_000,
  })
}

// the tab labels of SystemScreen and FirewallScreen, for "System › LEDs"
const TAB_LABELS: Record<string, string> = {
  access: 'Access',
  backup: 'Backup and reboot',
  cron: 'Scheduled tasks',
  custom: 'Custom rules',
  diagnostics: 'Diagnostics',
  forwards: 'Port forwards',
  ipsets: 'IP sets',
  iptables: 'Legacy iptables',
  leds: 'LEDs',
  logs: 'Logs',
  mounts: 'Mount points',
  nat: 'NAT rules',
  plugins: 'Plugins',
  processes: 'Processes',
  raw: 'Raw ruleset',
  rules: 'Traffic rules',
  services: 'Services',
  settings: 'System and time',
  status: 'Status',
}

/** Where a page with a screen here lives (src/openwrtgui/luci_bridge/pages.py NATIVE, NATIVE_TAB). */
export function nativeScreen(native: string, routerId: string, path?: string, tab?: string | null): { label: string; to: string } | null {
  const screen = screenOf(native, routerId, path)
  if (screen === null || !tab) return screen
  return { label: `${screen.label} › ${TAB_LABELS[tab] ?? tab}`, to: `${screen.to}?tab=${tab}` }
}

function screenOf(native: string, routerId: string, path?: string): { label: string; to: string } | null {
  if (native === 'wifi') return { label: 'Wi-Fi', to: `/routers/${routerId}/wifi` }
  if (native === 'dashboard') return { label: 'Dashboard', to: '/' }
  if (native === 'network') return { label: 'Network & DHCP', to: `/routers/${routerId}/network` }
  if (native === 'ports') return { label: 'Ports & VLANs', to: `/routers/${routerId}/ports` }
  if (native === 'firewall') return { label: 'Firewall', to: `/routers/${routerId}/firewall` }
  if (native === 'system') return { label: 'System', to: `/routers/${routerId}/system` }
  if (native === 'rf') {
    const label = path === 'admin/status/realtime/wireless' ? 'RF live' : 'RF live › Channel analysis'
    return { label, to: `/routers/${routerId}/rf` }
  }
  return null
}

export function luciPageLink(routerId: string, path: string): string {
  return `/routers/${routerId}/luci?page=${encodeURIComponent(path)}`
}
