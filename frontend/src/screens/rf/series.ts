import type { RfSample } from '../../api/types'

/** One hour of 1 s samples. */
export const MAX_POINTS = 3600

export type Point = { t: number; v: number | null }
export type StationSeries = { signal: Point[]; rx: Point[]; tx: Point[] }
export type Buffers = Record<string, StationSeries>
export type WindowS = 60 | 300 | 3600

const cap = (points: Point[]): Point[] => (points.length > MAX_POINTS ? points.slice(points.length - MAX_POINTS) : points)

/** A new set of buffers with this sample's points; stations missing from it get a gap. */
export function pushSample(b: Buffers, s: RfSample): Buffers {
  const t = Date.parse(s.at)
  const next: Buffers = {}
  const seen = new Set<string>()
  for (const st of s.stations) {
    seen.add(st.mac)
    const old = b[st.mac] ?? { signal: [], rx: [], tx: [] }
    next[st.mac] = {
      signal: cap([...old.signal, { t, v: st.signal_dbm }]),
      rx: cap([...old.rx, { t, v: st.rx?.mbps ?? null }]),
      tx: cap([...old.tx, { t, v: st.tx?.mbps ?? null }]),
    }
  }
  for (const [mac, old] of Object.entries(b)) {
    if (seen.has(mac)) continue
    next[mac] = {
      signal: cap([...old.signal, { t, v: null }]),
      rx: cap([...old.rx, { t, v: null }]),
      tx: cap([...old.tx, { t, v: null }]),
    }
  }
  return next
}

export function windowed(points: Point[], nowMs: number, windowS: number): Point[] {
  const from = nowMs - windowS * 1000
  return points.filter((p) => p.t >= from)
}

/** uPlot data columns: times in seconds, values (null = gap). */
export function toUplot(points: Point[]): [number[], (number | null)[]] {
  return [points.map((p) => p.t / 1000), points.map((p) => p.v)]
}
