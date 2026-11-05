import type { Mode } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { MODES, modeSummary, type ModeDraft } from './draft'

const LABEL: Record<Mode, string> = { b: '802.11b', g: '802.11g', n20: '802.11n · 20 MHz', n40: '802.11n · 40 MHz' }

function rates(mode: Mode, mcs: number[]): string {
  if (mode === 'b') return 'CCK 1 · 2 · 5.5 · 11'
  if (mode === 'g') return 'OFDM 6 – 54'
  const top = mcs.length > 0 ? Math.max(...mcs) : 7
  return `${mode === 'n40' ? 'HT40' : 'HT'} MCS 0–${top}`
}

function note(draft: ModeDraft, legacyRates: boolean): string | null {
  if (draft.kind === 'auto') {
    return legacyRates
      ? 'Auto keeps legacy_rates as it is (now 1), so the 802.11b rates stay on.'
      : 'Auto on this image means g + n only: OpenWrt keeps the 802.11b rates off unless legacy_rates=1.'
  }
  if (draft.kind !== 'set') return null
  const m = draft.modes
  const n = m.includes('n20') || m.includes('n40')
  if (n && !m.includes('b') && !m.includes('g')) {
    return '802.11n only: beacons and management frames still go out at 6 Mb/s OFDM, because 802.11 needs a legacy basic rate. Data frames are HT only.'
  }
  if (n && m.includes('b') && !m.includes('g')) {
    return 'b + n without g is an unusual mix. It is allowed: after Apply the app reads a real beacon and shows what the AP actually advertises.'
  }
  return null
}

type Props = { draft: ModeDraft; mcs: number[]; legacyRates: boolean; onChange: (d: ModeDraft) => void }

export function ModeCard({ draft, mcs, legacyRates, onChange }: Props) {
  const ticked: Mode[] = draft.kind === 'all' ? MODES : draft.kind === 'set' ? draft.modes : []
  const toggle = (mode: Mode): void => {
    const base: Mode[] = draft.kind === 'set' ? draft.modes : draft.kind === 'all' ? MODES : []
    onChange({ kind: 'set', modes: base.includes(mode) ? base.filter((x) => x !== mode) : [...base, mode] })
  }
  const text = note(draft, legacyRates)
  return (
    <section className="card stack" aria-labelledby="modes-h">
      <div className="row">
        <div className="hrow">
          <h2 id="modes-h">Modes</h2>
          <Help topic={HELP.wifiModes} />
        </div>
        <span className="b neu mono">{modeSummary(draft)}</span>
      </div>
      <div className="row">
        <div className="seg" role="group" aria-label="Mode preset">
          <button type="button" className={draft.kind === 'auto' ? 'on' : ''} aria-pressed={draft.kind === 'auto'} onClick={() => onChange({ kind: 'auto', modes: [] })}>
            Auto
          </button>
          <button type="button" className={draft.kind === 'all' ? 'on' : ''} aria-pressed={draft.kind === 'all'} onClick={() => onChange({ kind: 'all', modes: [] })}>
            All
          </button>
        </div>
        <span className="muted">or tick modes: the router then uses only the ticked ones</span>
      </div>
      <div className="tiles">
        {MODES.map((mode) => (
          <button key={mode} type="button" className={`tile${ticked.includes(mode) ? ' on' : ''}`} aria-pressed={ticked.includes(mode)} onClick={() => toggle(mode)}>
            <strong>{LABEL[mode]}</strong>
            <span className="muted mono">{rates(mode, mcs)}</span>
          </button>
        ))}
      </div>
      {draft.kind === 'custom' && <div className="note w">The modes were set outside the selector; see All options.</div>}
      {text && <div className="note">{text}</div>}
    </section>
  )
}
