import type { PortStats, PortTotals } from '../../api/types'

/** Switch counters are 32-bit (AP2's mt7620): they wrap at 2^32. */
const WRAP = 2 ** 32

export type Column = keyof PortTotals

/**
 * How much a counter grew between two reads (v1.2a R7). A counter lower than before wrapped when the earlier
 * value was at least 2^31; otherwise it was reset (a reboot or a clear), which is said, never a negative number.
 */
export function counterDelta(prev: number, cur: number): number | 'reset' {
  if (cur >= prev) return cur - prev
  if (prev >= 2 ** 31) return cur + WRAP - prev
  return 'reset'
}

function value(s: PortStats, num: number, column: Column): number | null {
  const port = s.ports.find((p) => p.num === num)
  return port ? port.totals[column] : null
}

/** Per second, between two reads; null when a value is missing or no time passed. */
export function rate(prev: PortStats, cur: PortStats, num: number, column: Column): number | 'reset' | null {
  const a = value(prev, num, column)
  const b = value(cur, num, column)
  const seconds = cur.read_at - prev.read_at
  if (a === null || b === null || seconds <= 0) return null
  const delta = counterDelta(a, b)
  return delta === 'reset' ? 'reset' : delta / seconds
}

/** How much a counter grew since the page's baseline read. */
export function sinceBaseline(base: PortStats, cur: PortStats, num: number, column: Column): number | 'reset' | null {
  const a = value(base, num, column)
  const b = value(cur, num, column)
  return a === null || b === null ? null : counterDelta(a, b)
}

function scaled(n: number, units: readonly string[], step: number): string {
  let i = 0
  let v = n
  while (v >= step && i < units.length - 1) {
    v /= step
    i += 1
  }
  return i === 0 ? `${Math.round(v)} ${units[0]}` : `${v.toFixed(1)} ${units[i]}`
}

export function formatBytes(bytes: number): string {
  return scaled(bytes, ['B', 'kB', 'MB', 'GB', 'TB'], 1000)
}

export function formatBits(bitsPerSecond: number): string {
  return scaled(bitsPerSecond, ['bit/s', 'kbit/s', 'Mbit/s', 'Gbit/s'], 1000)
}
