import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch, postJson } from '../../api/client'
import type { Bss, ScanPlanOut, ScanResult } from '../../api/types'
import { PreviewApply } from '../../components/PreviewApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { hhmm } from '../routerState'
import { ChannelChart } from './ChannelChart'

type Sort = 'signal' | 'channel' | 'ssid'
const SORTS: ReadonlyArray<readonly [Sort, string]> = [
  ['signal', 'Signal'],
  ['channel', 'Channel'],
  ['ssid', 'SSID'],
]

function sorted(networks: Bss[], by: Sort): Bss[] {
  const out = [...networks]
  if (by === 'channel') return out.sort((a, b) => (a.channel ?? 0) - (b.channel ?? 0))
  if (by === 'ssid') return out.sort((a, b) => (a.ssid ?? '￿').localeCompare(b.ssid ?? '￿'))
  return out.sort((a, b) => (b.signal_dbm ?? -999) - (a.signal_dbm ?? -999))
}

function width(b: Bss): string {
  return b.width_mhz === 40 ? `40 MHz (${b.secondary === 'above' ? '+' : '−'})` : '20 MHz'
}

/** Channel analysis (spec 7.3, LuCI's Status › Channel analysis; plan D13): a passive scan on demand. */
export function ChannelAnalysis({ routerId, radio }: { routerId: string; radio: string }) {
  const client = useQueryClient()
  const base = `/api/routers/${routerId}/rf/${radio}/scan`
  const last = useQuery({ queryKey: ['scan', routerId, radio], queryFn: () => apiFetch<ScanResult | null>(base) })
  const [plan, setPlan] = useState<ScanPlanOut | null>(null)
  const [by, setBy] = useState<Sort>('signal')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const result = last.data ?? null

  const act = async (fn: () => Promise<void>): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err))
    } finally {
      setBusy(false)
    }
  }
  const ask = (): Promise<void> => act(async () => setPlan(await postJson<ScanPlanOut>(`${base}/preview`)))
  const scan = (): Promise<void> =>
    act(async () => {
      if (!plan) return
      client.setQueryData(['scan', routerId, radio], await postJson<ScanResult>(base, { digest: plan.digest }))
      setPlan(null)
    })

  return (
    <section className="card stack" aria-labelledby="channels-scan-h">
      <div className="hrow">
        <h2 id="channels-scan-h">Channel analysis</h2>
        <Help topic={HELP.rfChannels} />
      </div>
      <span className="muted">
        A passive scan: the radio listens on every channel in turn and sends nothing. The busy share of each channel is what the radio
        heard there during the scan.
      </span>
      {!plan && (
        <div className="row">
          <button className="btn" type="button" disabled={busy} onClick={() => void ask()}>
            Scan…
          </button>
          {result && (
            <span className="muted">
              Last scan {hhmm(result.at)} via {result.via === 'ap' ? 'the AP interface' : 'a temporary interface'} · {result.seconds.toFixed(1)} s
            </span>
          )}
        </div>
      )}
      {plan && (
        <PreviewApply
          heading="Commands that will run"
          lines={plan.lines}
          warnings={plan.warnings}
          error={error}
          isBusy={busy}
          applyLabel="Scan now"
          onApply={() => void scan()}
          helpTopic={HELP.rfChannels}
        />
      )}
      {!plan && error && (
        <div className="note x" role="alert">
          {error}
        </div>
      )}
      {result && <ChannelChart result={result} />}
      {result && result.networks.length === 0 && <div className="muted">No networks heard.</div>}
      {result && result.networks.length > 0 && (
        <>
          <div className="seg" role="group" aria-label="Sort networks by">
            {SORTS.map(([value, label]) => (
              <button key={value} type="button" className={by === value ? 'on' : ''} aria-pressed={by === value} onClick={() => setBy(value)}>
                {label}
              </button>
            ))}
          </div>
          <div className="scroll-x">
            <table className="tbl" aria-label="Networks heard">
              <thead>
                <tr>
                  <th>SSID</th>
                  <th>BSSID</th>
                  <th>Channel</th>
                  <th>Width</th>
                  <th>Signal</th>
                  <th>Security</th>
                </tr>
              </thead>
              <tbody>
                {sorted(result.networks, by).map((b) => (
                  <tr key={b.bssid}>
                    <td>
                      {b.ssid ?? <span className="muted">(hidden)</span>} {b.own && <span className="b neu">own</span>}
                    </td>
                    <td className="mono">{b.bssid}</td>
                    <td className="mono">{b.channel ?? '?'}</td>
                    <td className="mono">{width(b)}</td>
                    <td className="mono">{b.signal_dbm === null ? '—' : `${b.signal_dbm.toFixed(0)} dBm`}</td>
                    <td>{b.security}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
