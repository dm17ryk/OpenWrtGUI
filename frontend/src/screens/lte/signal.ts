import type { LteMeasure, LteSample, LteState } from '../../api/types'
import { MAX_POINTS, type Point } from '../rf/series'

export type Metric = 'rssi' | 'rsrp' | 'rsrq' | 'snr'
export type Quality = 'excellent' | 'good' | 'fair' | 'poor'
export type LteSeries = Record<Metric, Point[]>

export const METRICS: ReadonlyArray<{ key: Metric; label: string; unit: 'dBm' | 'dB' }> = [
  { key: 'rssi', label: 'RSSI', unit: 'dBm' },
  { key: 'rsrp', label: 'RSRP', unit: 'dBm' },
  { key: 'rsrq', label: 'RSRQ', unit: 'dB' },
  { key: 'snr', label: 'SNR', unit: 'dB' },
]

/** The same table as src/openwrtgui/lte/quality.py (v0.6a plan D11): the lowest value of excellent, good, fair. */
const THRESHOLDS: Record<Metric, readonly [number, number, number]> = {
  rsrp: [-80, -90, -100],
  rsrq: [-10, -15, -20],
  snr: [20, 13, 0],
  rssi: [-65, -75, -85],
}

/** A value on a boundary gets the better label. */
export function quality(metric: Metric, value: number): Quality {
  const [excellent, good, fair] = THRESHOLDS[metric]
  if (value >= excellent) return 'excellent'
  if (value >= good) return 'good'
  if (value >= fair) return 'fair'
  return 'poor'
}

export const EMPTY_SERIES: LteSeries = { rssi: [], rsrp: [], rsrq: [], snr: [] }

const cap = (points: Point[]): Point[] => (points.length > MAX_POINTS ? points.slice(points.length - MAX_POINTS) : points)

/** New series with this sample's points; a value the modem did not give is a gap. */
export function pushLte(series: LteSeries, s: LteSample): LteSeries {
  const t = s.t * 1000
  return {
    rssi: cap([...series.rssi, { t, v: s.rssi }]),
    rsrp: cap([...series.rsrp, { t, v: s.rsrp }]),
    rsrq: cap([...series.rsrq, { t, v: s.rsrq }]),
    snr: cap([...series.snr, { t, v: s.snr }]),
  }
}

/** The value to show now: the latest live sample when there is one (labelled only on LTE), else the read. */
export function current(metric: Metric, state: LteState, sample: LteSample | null): LteMeasure | null {
  if (!sample) return state[metric] ?? null
  const value = sample[metric]
  if (value == null) return null
  return { value, label: sample.radio === 'lte' ? quality(metric, value) : null }
}
