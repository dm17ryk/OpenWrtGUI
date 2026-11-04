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

/** "−52 dBm" with a real minus sign, as on the mockups. */
export function dbm(value: number): string {
  return `${value < 0 ? '−' : ''}${Math.abs(value)} dBm`
}

export function hhmm(iso: string): string {
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? '' : 's'}`
}

export function stationCount(status: RouterStatus | null | undefined): number {
  return status ? status.radios.reduce((sum, r) => sum + r.stations.length, 0) : 0
}
