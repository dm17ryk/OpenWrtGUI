import type { SystemSample } from '../../api/types'
import { MAX_POINTS, type Point } from '../rf/series'

/** What the Status tab draws: load, per-interface rates and the connection count, one point per sample. */
export type SystemSeries = {
  load1: Point[]
  load15: Point[]
  connections: Point[]
  rx: Record<string, Point[]>
  tx: Record<string, Point[]>
}

export const EMPTY_SYSTEM: SystemSeries = { load1: [], load15: [], connections: [], rx: {}, tx: {} }

const cap = (points: Point[]): Point[] => (points.length > MAX_POINTS ? points.slice(points.length - MAX_POINTS) : points)

/** kbit/s from bytes per second. */
export const kbits = (bytesPerS: number): number => Math.round((bytesPerS * 8) / 100) / 10

function pushRates(by: Record<string, Point[]>, t: number, rates: SystemSample['rates'], at: 0 | 1): Record<string, Point[]> {
  const out: Record<string, Point[]> = { ...by }
  for (const [name, pair] of Object.entries(rates)) out[name] = cap([...(by[name] ?? []), { t, v: kbits(pair[at]) }])
  return out
}

/** New series with this sample; a value the router did not give is a gap. */
export function pushSystem(series: SystemSeries, s: SystemSample): SystemSeries {
  const t = s.t * 1000
  return {
    load1: cap([...series.load1, { t, v: s.load1 }]),
    load15: cap([...series.load15, { t, v: s.load15 }]),
    connections: cap([...series.connections, { t, v: s.connections }]),
    rx: pushRates(series.rx, t, s.rates, 0),
    tx: pushRates(series.tx, t, s.rates, 1),
  }
}

/** "7.3 MiB" from bytes. */
export const mib = (bytes: number): string => `${(bytes / 1048576).toFixed(1)} MiB`
