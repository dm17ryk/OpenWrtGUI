import { useState } from 'react'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { RfChart } from '../rf/RfChart'
import { windowed, type WindowS } from '../rf/series'
import { METRICS, type LteSeries } from './signal'

const WINDOWS: ReadonlyArray<readonly [WindowS, string]> = [
  [60, '1 min'],
  [300, '5 min'],
  [3600, '1 h'],
]

type Props = { series: LteSeries; nowMs: number }

/** RSSI, RSRP, RSRQ and SNR over the chosen window; one sample every 10 s while the screen is open. */
export function SignalCharts({ series, nowMs }: Props) {
  const [windowS, setWindowS] = useState<WindowS>(300)
  return (
    <section className="card stack" aria-labelledby="lte-live-h">
      <div className="row">
        <div className="hrow">
          <h2 id="lte-live-h">Live signal</h2>
          <Help topic={HELP.lteCharts} />
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
        {METRICS.map((m) => (
          <RfChart key={m.key} title={m.label} unit={m.unit} series={[{ label: m.label, tone: 'rx', points: windowed(series[m.key], nowMs, windowS) }]} />
        ))}
      </div>
    </section>
  )
}
