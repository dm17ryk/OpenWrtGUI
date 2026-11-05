import type { RadioState, Security } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { SECURITY_LABEL, widthText, type Draft, type SsidDraft } from './draft'

const SECURITIES: Exclude<Security, 'other'>[] = ['open', 'wpa2', 'wpa3', 'wpa2_wpa3']

type Props = { radio: RadioState; draft: Draft; onChange: (d: Draft) => void }

function allowedSecurity(radio: RadioState, s: Exclude<Security, 'other'>): boolean {
  if (radio.band === '6g') return s === 'wpa3'
  return radio.limits.sae || (s !== 'wpa3' && s !== 'wpa2_wpa3')
}

export function RadioFields({ radio, draft, onChange }: Props) {
  const tx = draft.txpower
  const setSsid = (section: string, change: Partial<SsidDraft>): void =>
    onChange({ ...draft, ssids: { ...draft.ssids, [section]: { ...draft.ssids[section], ...change } } })
  const actual = radio.actual?.txpower_dbm
  const top = Math.max(...radio.limits.txpower_dbm)
  return (
    <>
      <section className="card stack" aria-labelledby="power-h">
        <div className="grid">
          <div className="field">
            <label htmlFor="width-out">Width</label>
            <output id="width-out" className="mono">
              {widthText(draft.modes)}
            </output>
          </div>
          <div className="field">
            <div className="hrow">
              <h2 id="power-h" style={{ fontSize: 13 }}>
                TX power
              </h2>
              <Help topic={HELP.wifiTxPower} />
            </div>
            <div className="row">
              <div className="seg" role="group" aria-label="TX power">
                <button type="button" className={tx.kind === 'auto' ? 'on' : ''} aria-pressed={tx.kind === 'auto'} onClick={() => onChange({ ...draft, txpower: { kind: 'auto', dbm: null } })}>
                  Auto
                </button>
                <button type="button" className={tx.kind === 'fixed' ? 'on' : ''} aria-pressed={tx.kind === 'fixed'} onClick={() => onChange({ ...draft, txpower: { kind: 'fixed', dbm: tx.dbm ?? top } })}>
                  Fixed
                </button>
              </div>
              {tx.kind === 'fixed' && (
                <select className="in" aria-label="TX power in dBm" value={tx.dbm ?? top} onChange={(e) => onChange({ ...draft, txpower: { kind: 'fixed', dbm: Number(e.target.value) } })}>
                  {radio.limits.txpower_dbm.map((d) => (
                    <option key={d} value={d}>
                      {d} dBm
                    </option>
                  ))}
                </select>
              )}
            </div>
            <span className="muted">{actual != null ? `actual ${actual.toFixed(2)} dBm` : tx.kind === 'auto' ? `up to ${top} dBm` : 'actual: radio off'}</span>
          </div>
          <div className="field">
            <label htmlFor="country-out">Country</label>
            <output id="country-out" className="row" style={{ gap: 6 }}>
              <span className="mono">{radio.limits.country}</span>
              {radio.writers.country && <span className="b har">set by {radio.writers.country}</span>}
            </output>
          </div>
        </div>
      </section>
      <section className="card stack" aria-labelledby="ssid-h">
        <div className="hrow">
          <h2 id="ssid-h">SSID and security</h2>
          <Help topic={HELP.wifiSecurity} />
        </div>
        {radio.ssids.map((s) => {
          const d = draft.ssids[s.section]
          return (
            <div key={s.section} className="grid">
              <div className="field">
                <label htmlFor={`ssid-${s.section}`}>SSID</label>
                <input id={`ssid-${s.section}`} className="in" value={d.ssid} maxLength={32} onChange={(e) => setSsid(s.section, { ssid: e.target.value })} />
              </div>
              <div className="field">
                <span>Security</span>
                <div className="seg" role="group" aria-label={`Security of ${s.ssid}`}>
                  {SECURITIES.map((sec) => (
                    <button
                      key={sec}
                      type="button"
                      className={d.security === sec ? 'on' : ''}
                      aria-pressed={d.security === sec}
                      disabled={!allowedSecurity(radio, sec)}
                      onClick={() => setSsid(s.section, { security: sec })}
                    >
                      {SECURITY_LABEL[sec]}
                    </button>
                  ))}
                </div>
              </div>
              {d.security !== 'open' && (
                <div className="field">
                  <label htmlFor={`key-${s.section}`}>Key for {s.ssid}</label>
                  <input
                    id={`key-${s.section}`}
                    className="in"
                    type="password"
                    autoComplete="new-password"
                    value={d.key}
                    placeholder={s.key_set ? 'key kept as is, never shown' : 'enter a key'}
                    onChange={(e) => setSsid(s.section, { key: e.target.value })}
                  />
                </div>
              )}
            </div>
          )
        })}
      </section>
    </>
  )
}
