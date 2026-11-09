import { useState } from 'react'
import { ApiError, postJson } from '../../api/client'
import type { ModemInfo } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'

type Props = { routerId: string; modem: ModemInfo; opmode?: string | null }

/** The modem's own details. The IMEI is read only when asked for (D3) and kept only on screen. */
export function ModemCard({ routerId, modem, opmode }: Props) {
  const [imei, setImei] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isBusy, setBusy] = useState(false)
  const reveal = async (): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      setImei((await postJson<{ imei: string }>(`/api/routers/${routerId}/lte/imei`)).imei)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err))
    } finally {
      setBusy(false)
    }
  }
  const rows: ReadonlyArray<readonly [string, string]> = [
    ['Manufacturer', modem.manufacturer ?? '—'],
    ['Model', modem.model ?? '—'],
    ['Firmware', modem.firmware ?? '—'],
    ['Operating mode', opmode ?? '—'],
    ['Mode order', modem.mode_order != null ? `${modem.mode_order} (names not mapped yet)` : '—'],
    ['AT port', modem.at_port ?? 'none answered'],
  ]
  return (
    <section className="card stack" aria-labelledby="lte-modem-h">
      <div className="hrow">
        <h2 id="lte-modem-h">Modem</h2>
        <Help topic={HELP.lteModem} />
      </div>
      <dl className="kv">
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: 'contents' }}>
            <dt>{k}</dt>
            <dd className="mono">{v}</dd>
          </div>
        ))}
        <dt>IMEI</dt>
        <dd className="row" style={{ gap: 8 }}>
          <span className="mono">{imei ?? '••••'}</span>
          {imei ? (
            <button className="btn" type="button" onClick={() => setImei(null)}>
              Hide
            </button>
          ) : (
            <button className="btn" type="button" disabled={isBusy} onClick={() => void reveal()}>
              Reveal
            </button>
          )}
        </dd>
      </dl>
      {error && (
        <div className="note x" role="alert">
          {error}
        </div>
      )}
    </section>
  )
}
