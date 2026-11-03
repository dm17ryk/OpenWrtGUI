import type { RadioStatus, RouterItem, RouterStatus } from '../api/types'

export type RouterState = 'on air' | 'parked' | 'unreachable' | 'needs app key' | 'connecting'

export function routerState(item: RouterItem): RouterState {
  if (item.record.auth === 'none') return 'needs app key'
  if (item.status) return item.status.radios.some((r) => r.up) ? 'on air' : 'parked'
  if (!item.health.online && item.health.error && item.health.error !== 'not connected yet') return 'unreachable'
  return 'connecting'
}

export function radioText(r: RadioStatus): string {
  if (r.up) return `ch ${r.channel ?? '?'} · ${r.htmode ?? ''} · ${r.txpower_dbm ?? '?'} dBm`
  return `staged ch ${r.channel ?? '?'} · ${r.htmode ?? ''} · radio off`
}

export function radioLine(status: RouterStatus): string {
  const up = status.radios.find((r) => r.up)
  if (up) {
    const n = up.stations.length
    return `ch ${up.channel ?? '?'} ${up.htmode ?? ''} · ${n} sta`
  }
  return 'parked'
}

export function stationCount(status: RouterStatus | null | undefined): number {
  return status ? status.radios.reduce((sum, r) => sum + r.stations.length, 0) : 0
}
