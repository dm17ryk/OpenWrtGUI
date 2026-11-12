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

/** Where a page with a screen here lives (src/openwrtgui/luci_bridge/pages.py NATIVE). */
export function nativeScreen(native: string, routerId: string): { label: string; to: string } | null {
  if (native === 'wifi') return { label: 'Wi-Fi', to: `/routers/${routerId}/wifi` }
  if (native === 'dashboard') return { label: 'Dashboard', to: '/' }
  if (native === 'network') return { label: 'Network & DHCP', to: `/routers/${routerId}/network` }
  if (native === 'ports') return { label: 'Ports & VLANs', to: `/routers/${routerId}/ports` }
  if (native === 'firewall') return { label: 'Firewall', to: `/routers/${routerId}/firewall` }
  if (native === 'system') return { label: 'System', to: `/routers/${routerId}/system` }
  if (native === 'rf') return { label: 'RF live › Channel analysis', to: `/routers/${routerId}/rf` }
  return null
}

export function luciPageLink(routerId: string, path: string): string {
  return `/routers/${routerId}/luci?page=${encodeURIComponent(path)}`
}
