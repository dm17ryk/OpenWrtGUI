import { useState } from 'react'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { RfChart } from '../rf/RfChart'
import { windowed, type WindowS } from '../rf/series'
import type { SystemSeries } from './live'

const WINDOWS: ReadonlyArray<readonly [WindowS, string]> = [
  [60, '1 min'],
  [300, '5 min'],
  [3600, '1 h'],
]

type Props = { series: SystemSeries; nowMs: number }

/** Load, one interface's traffic and the connection count, one sample every 3 s while the tab is open. */
export function LiveCharts({ series, nowMs }: Props) {
  const [windowS, setWindowS] = useState<WindowS>(300)
  const [picked, setPicked] = useState<string | null>(null)
  const [openedMs] = useState(() => Date.now()) // the axis end until the first sample arrives
  const end = (nowMs || openedMs) / 1000
  const xRange = [end - windowS, end] as const
  const names = Object.keys(series.rx).sort()
  const iface = picked !== null && names.includes(picked) ? picked : (names[0] ?? null)
  const cut = (points: SystemSeries['load1']) => windowed(points, nowMs, windowS)
  return (
    <section className="card stack" aria-labelledby="system-live-h">
      <div className="row">
        <div className="hrow">
          <h2 id="system-live-h">Live load, bandwidth and connections</h2>
          <Help topic={HELP.systemLive} />
        </div>
        <div className="spacer" />
        <div className="seg" role="group" aria-label="Window">
          {WINDOWS.map(([w, label]) => (
            <button key={w} type="button" className={windowS === w ? 'on' : ''} aria-pressed={windowS === w} onClick={() => setWindowS(w)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="rf-cols">
        <RfChart
          title="Load"
          unit="load"
          xRange={xRange}
          series={[
            { label: '1 min', tone: 'rx', points: cut(series.load1) },
            { label: '15 min', tone: 'tx', points: cut(series.load15) },
          ]}
        />
        <div className="stack">
          <label className="field">
            <span>Interface</span>
            <select value={iface ?? ''} onChange={(e) => setPicked(e.target.value)} disabled={names.length === 0}>
              {names.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <RfChart
            title="Bandwidth"
            unit="kbit/s"
            xRange={xRange}
            series={[
              { label: 'received', tone: 'rx', points: iface ? cut(series.rx[iface] ?? []) : [] },
              { label: 'sent', tone: 'tx', points: iface ? cut(series.tx[iface] ?? []) : [] },
            ]}
          />
        </div>
        <RfChart title="Connections" unit="count" xRange={xRange} series={[{ label: 'tracked', tone: 'rx', points: cut(series.connections) }]} />
      </div>
    </section>
  )
}
