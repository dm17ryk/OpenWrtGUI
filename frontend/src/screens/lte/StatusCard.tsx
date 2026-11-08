import type { LteMeasure, LteSample, LteState } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { uptimeText } from '../net/rows'
import { dbm } from '../routerState'
import { current, METRICS, type Quality } from './signal'

const CHIP: Record<Quality, string> = { excellent: 'b air', good: 'b air', fair: 'b park', poor: 'b bad' }
const RADIO: Record<string, string> = { lte: 'LTE', umts: 'UMTS', gsm: 'GSM', cdma: 'CDMA', 'cdma-1x': 'CDMA 1x' }

function bytes(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  const units = ['KiB', 'MiB', 'GiB', 'TiB']
  let value = n / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(1)} ${units[unit]}`
}

function session(s: LteState): string {
  if (s.up) return s.uptime_s != null ? `up · ${uptimeText(s.uptime_s)}` : 'up'
  if (s.pending) return 'connecting'
  return s.up === false ? 'down' : '—'
}

function operator(s: LteState): string {
  if (!s.operator) return '—'
  return s.operator_source === 'qmi' ? `${s.operator} (from QMI, may be garbled)` : s.operator
}

function network(s: LteState): string {
  return s.mcc != null && s.mnc != null ? `${s.mcc} / ${String(s.mnc).padStart(2, '0')}` : '—'
}

function valueText(unit: 'dBm' | 'dB', m: LteMeasure): string {
  return unit === 'dBm' ? dbm(m.value) : `${m.value < 0 ? '−' : ''}${Math.abs(m.value)} dB`
}

function SignalTile({ label, unit, measure }: { label: string; unit: 'dBm' | 'dB'; measure: LteMeasure | null }) {
  return (
    <section className="card stack rf-tile" aria-label={label}>
      <span className="eyebrow">{label}</span>
      <strong className="mono">{measure ? valueText(unit, measure) : '—'}</strong>
      {measure?.label ? <span className={CHIP[measure.label]}>{measure.label}</span> : <span className="muted">{measure ? 'no label off LTE' : 'no value'}</span>}
    </section>
  )
}

type Props = { state: LteState; sample: LteSample | null }

/** The four signal values with their labels: the latest live sample, or the screen's read until one comes. */
export function SignalTiles({ state, sample }: Props) {
  return (
    <>
      <div className="hrow">
        <h2>Signal quality</h2>
        <Help topic={HELP.lteSignal} />
      </div>
      <div className="rf-tiles">
        {METRICS.map((m) => (
          <SignalTile key={m.key} label={m.label} unit={m.unit} measure={current(m.key, state, sample)} />
        ))}
      </div>
    </>
  )
}

/** Registration, radio, operator and the data session. */
export function StatusCard({ state, sample }: Props) {
  const registration = sample?.registration ?? state.registration
  const radio = sample?.radio ?? state.radio
  const rows: ReadonlyArray<readonly [string, string]> = [
    ['Registration', registration ?? '—'],
    ['Radio', radio ? (RADIO[radio] ?? radio) : '—'],
    ['Roaming', state.roaming == null ? '—' : state.roaming ? 'yes' : 'no'],
    ['Operator', operator(state)],
    ['MCC / MNC', network(state)],
    ['Session', session(state)],
    ['IPv4', state.ipv4 ?? '—'],
    ['RX / TX', `${bytes(state.rx_bytes)} / ${bytes(state.tx_bytes)}`],
  ]
  return (
    <section className="card stack" aria-labelledby="lte-status-h">
      <div className="hrow">
        <h2 id="lte-status-h">Status</h2>
        <Help topic={HELP.lteStatus} />
      </div>
      <dl className="kv">
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: 'contents' }}>
            <dt>{k}</dt>
            <dd className="mono">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
