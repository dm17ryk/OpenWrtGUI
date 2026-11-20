import type { PortCounters, PortStats, PortTotals } from '../../api/types'

export type Column = keyof PortTotals
export type Since = Record<number, Record<Column, number | null>>

const COLUMNS: readonly Column[] = ['rx_packets', 'rx_bytes', 'rx_errors', 'tx_packets', 'tx_bytes', 'tx_errors']
const SLACK = 1.05 // a little over the link speed is still the link (counters are read a moment apart)

/**
 * How much a counter grew between two reads (v1.2a R7, final review C1). A counter lower than before wrapped when
 * the earlier value was at least half its range (2^(bits-1)); otherwise it was reset (a reboot or a clear), which
 * is said, never a negative number. The mt7620 counts packets and errors in 16 bits, octets in 32.
 */
export function counterDelta(prev: number, cur: number, bits = 32): number | 'reset' {
  if (cur >= prev) return cur - prev
  if (prev >= 2 ** (bits - 1)) return cur + 2 ** bits - prev
  return 'reset'
}

function names(port: PortCounters, column: Column): string[] {
  return Object.entries(port.columns)
    .filter(([, c]) => c === column)
    .map(([name]) => name)
}

/** The most a column can grow in `seconds` at the port's link speed; null when the speed is not known. */
function ceiling(port: PortCounters, column: Column, seconds: number): number | null {
  if (!port.speed_mbps) return null
  const bitsPerSecond = port.speed_mbps * 1_000_000 * SLACK
  // a byte column carries at most the link's bytes; a packet or error column at most minimum-size frames (64 B)
  const perSecond = column.endsWith('bytes') ? bitsPerSecond / 8 : bitsPerSecond / (64 * 8)
  return perSecond * seconds
}

/** How much a column grew from one read to the next: each of its counters at its own width, added up. */
function step(prev: PortCounters, cur: PortCounters, column: Column, seconds: number): number | 'reset' | null {
  const counted = names(cur, column).filter((n) => n in prev.raw && n in cur.raw)
  if (counted.length === 0) return null
  let total = 0
  for (const name of counted) {
    const d = counterDelta(prev.raw[name], cur.raw[name], cur.bits[name] ?? 32)
    if (d === 'reset') return 'reset'
    total += d
  }
  const most = ceiling(cur, column, seconds)
  return most !== null && total > most ? 'reset' : total // faster than the link: a reboot, not a wrap
}

function port(s: PortStats, num: number): PortCounters | undefined {
  return s.ports.find((p) => p.num === num)
}

/** Per second, between two reads; null when a value is missing or no time passed. */
export function rate(prev: PortStats, cur: PortStats, num: number, column: Column): number | 'reset' | null {
  const a = port(prev, num)
  const b = port(cur, num)
  const seconds = cur.read_at - prev.read_at
  if (!a || !b || seconds <= 0) return null
  const s = step(a, b, column, seconds)
  return s === null || s === 'reset' ? s : s / seconds
}

/** Zero for every column a port counts, null for the others: the counts at the page's baseline. */
export function emptySince(base: PortStats): Since {
  const out: Since = {}
  for (const p of base.ports) {
    out[p.num] = Object.fromEntries(COLUMNS.map((c) => [c, names(p, c).length ? 0 : null])) as Record<Column, number | null>
  }
  return out
}

/**
 * The counts since the baseline, one more read in: each column adds its step, so wraps add up however many there
 * are (final review I1). After a reset the counters start from zero, so their values now are what came since.
 */
export function accumulate(since: Since, prev: PortStats, cur: PortStats): Since {
  const seconds = cur.read_at - prev.read_at
  const out: Since = {}
  for (const b of cur.ports) {
    const a = port(prev, b.num)
    const before = since[b.num]
    if (!a || !before) {
      out[b.num] = before ?? emptySince({ ...cur, ports: [b] })[b.num]
      continue
    }
    const next = { ...before }
    for (const column of COLUMNS) {
      const was = before[column]
      if (was === null) continue
      const s = step(a, b, column, seconds)
      if (s === null) continue
      const restarted = names(b, column).reduce((sum, n) => sum + (b.raw[n] ?? 0), 0)
      next[column] = was + (s === 'reset' ? restarted : s)
    }
    out[b.num] = next
  }
  return out
}

function scaled(n: number, units: readonly string[], unit: number): string {
  let i = 0
  let v = n
  while (v >= unit && i < units.length - 1) {
    v /= unit
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
