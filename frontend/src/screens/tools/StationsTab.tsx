import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { ApiError, apiFetch, postJson } from '../../api/client'
import type { ActionResult, ApStations, NeighbourEntry, StationAction, StationsView, ToolPlan } from '../../api/types'
import { PreviewApply } from '../../components/PreviewApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { usePreview } from '../wifi/usePreview'

const NO_METHOD = (method: string) => `This router's hostapd has no ${method}: it needs a full wpad build.`

function errorText(e: unknown): string {
  return e instanceof ApiError ? e.detail : String(e)
}

function action(kind: StationAction['kind'], ifname: string, patch: Partial<StationAction> = {}): StationAction {
  return { kind, ifname, mac: null, target: null, neighbours: [], ...patch }
}

function Outcome({ result }: { result: ActionResult }) {
  return (
    <div className="stack" style={{ gap: 8 }}>
      {result.ok ? (
        <div className="note ok">{result.detail}</div>
      ) : (
        <div className="note x" role="alert">
          {result.detail}
        </div>
      )}
      {result.status_code != null && <div>{`Status code ${result.status_code}`}</div>}
      {result.beacons.length > 0 && (
        <div className="scroll-x">
          <table className="tbl" aria-label="Beacon report">
            <thead>
              <tr>
                <th>BSSID</th>
                <th>Channel</th>
                <th>Signal (dBm)</th>
                <th>RSNI</th>
              </tr>
            </thead>
            <tbody>
              {result.beacons.map((b, i) => (
                // a station may report one BSSID on two channels
                // eslint-disable-next-line react/no-array-index-key
                <tr key={i}>
                  <td className="mono">{b.bssid ?? '—'}</td>
                  <td className="mono">{b.channel ?? '—'}</td>
                  <td className="mono">{b.rcpi_dbm ?? '—'}</td>
                  <td className="mono">{b.rsni ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function Neighbours({ ap, candidates, onPick }: { ap: ApStations; candidates: NeighbourEntry[]; onPick: (a: StationAction) => void }) {
  const [chosen, setChosen] = useState<string[]>([])
  const toggle = (bssid: string) =>
    setChosen(chosen.includes(bssid) ? chosen.filter((b) => b !== bssid) : [...chosen, bssid])
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="eyebrow">Neighbour report</div>
      {ap.neighbours.length > 0 ? (
        <ul>
          {ap.neighbours.map((n) => (
            <li key={n.bssid} className="mono">{`${n.bssid} ${n.ssid}`}</li>
          ))}
        </ul>
      ) : (
        <div className="muted">No neighbour set.</div>
      )}
      {ap.methods.includes('rrm_nr_set') ? (
        <>
          <fieldset>
            <legend>Set from the routers in this app</legend>
            {candidates.map((c) => (
              <label key={c.bssid} style={{ display: 'block' }}>
                <input type="checkbox" checked={chosen.includes(c.bssid)} onChange={() => toggle(c.bssid)} />{' '}
                {`${c.source} (${c.bssid})`}
              </label>
            ))}
          </fieldset>
          <div className="row" style={{ gap: 8 }}>
            <button className="btn" type="button" disabled={chosen.length === 0} onClick={() => onPick(action('neighbours', ap.ifname, { neighbours: chosen }))}>
              Set neighbour report
            </button>
            <button className="btn" type="button" onClick={() => onPick(action('neighbours', ap.ifname))}>
              Clear
            </button>
          </div>
        </>
      ) : (
        <div className="muted">{NO_METHOD('rrm_nr_set')}</div>
      )}
    </div>
  )
}

/** One AP: its stations and their requests, its neighbour report, and the one request being previewed. */
function ApSection({ routerId, ap, candidates }: { routerId: string; ap: ApStations; candidates: NeighbourEntry[] }) {
  const id = useId()
  const client = useQueryClient()
  const [picked, setPicked] = useState<StationAction | null>(null)
  const [targets, setTargets] = useState<Record<string, string>>({})
  const [result, setResult] = useState<ActionResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isBusy, setBusy] = useState(false)
  const preview = usePreview<ToolPlan>(`/api/routers/${routerId}/tools/stations/preview`, picked)
  const plan = preview?.plan ?? null
  const transition = ap.methods.includes('bss_transition_request')
  const beacon = ap.methods.includes('rrm_beacon_req')

  function pick(a: StationAction) {
    setResult(null)
    setError(null)
    setPicked(a)
  }

  async function apply() {
    if (!picked || !plan) return
    setBusy(true)
    try {
      setResult(await postJson<ActionResult>(`/api/routers/${routerId}/tools/stations/apply`, { ...picked, digest: plan.digest }))
      setPicked(null)
      void client.invalidateQueries({ queryKey: ['tool-stations', routerId] })
    } catch (e) {
      setError(errorText(e))
    }
    setBusy(false)
  }

  return (
    <section className="stack" aria-labelledby={`${id}-h`}>
      <h3 id={`${id}-h`}>{`${ap.ssid} (${ap.ifname}, channel ${ap.channel ?? '?'})`}</h3>
      {!transition && <div className="muted">{NO_METHOD('bss_transition_request')}</div>}
      {!beacon && <div className="muted">{NO_METHOD('rrm_beacon_req')}</div>}
      {ap.stations.length === 0 ? (
        <div className="muted">No station is connected.</div>
      ) : (
        <div className="scroll-x">
          <table className="tbl" aria-label={`Stations on ${ap.ifname}`}>
            <thead>
              <tr>
                <th>Station</th>
                <th>Name</th>
                <th>IP</th>
                <th>Signal (dBm)</th>
                <th>Requests</th>
              </tr>
            </thead>
            <tbody>
              {ap.stations.map((s) => {
                const target = targets[s.mac] ?? candidates[0]?.bssid ?? ''
                return (
                  <tr key={s.mac}>
                    <td className="mono">{s.mac}</td>
                    <td>{s.name ?? '—'}</td>
                    <td className="mono">{s.ip ?? '—'}</td>
                    <td className="mono">{s.signal_dbm ?? '—'}</td>
                    <td>
                      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                        {transition && (
                          <>
                            <select aria-label={`Target for ${s.mac}`} value={target} onChange={(e) => setTargets({ ...targets, [s.mac]: e.target.value })}>
                              {candidates.map((c) => (
                                <option key={c.bssid} value={c.bssid}>{`${c.source} (${c.bssid})`}</option>
                              ))}
                            </select>
                            <button
                              className="btn"
                              type="button"
                              aria-label={`BSS transition request to ${s.mac}`}
                              disabled={!target}
                              onClick={() => pick(action('transition', ap.ifname, { mac: s.mac, target }))}
                            >
                              BSS transition request
                            </button>
                          </>
                        )}
                        {beacon && (
                          <button
                            className="btn"
                            type="button"
                            aria-label={`Beacon report request to ${s.mac}`}
                            onClick={() => pick(action('beacon', ap.ifname, { mac: s.mac }))}
                          >
                            Beacon report request
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <Neighbours ap={ap} candidates={candidates} onPick={pick} />
      {picked && (
        <PreviewApply
          heading="Preview"
          lines={plan?.lines ?? []}
          warnings={plan?.warnings ?? []}
          error={error ?? preview?.error ?? null}
          isBusy={isBusy}
          applyLabel="Apply"
          onApply={() => void apply()}
          helpTopic={HELP.toolsStations}
        />
      )}
      {!picked && error && (
        <div className="note x" role="alert">
          {error}
        </div>
      )}
      {result && <Outcome result={result} />}
    </section>
  )
}

/**
 * Station management (v1.2b R8-R10): per AP, its stations and hostapd's 802.11v and 802.11k requests, each with an
 * exact preview. The candidates are this router's APs and every other router's APs in the app.
 */
export function StationsTab({ routerId }: { routerId: string }) {
  const id = useId()
  const view = useQuery({
    queryKey: ['tool-stations', routerId],
    queryFn: () => apiFetch<StationsView>(`/api/routers/${routerId}/tools/stations`),
  })
  const data = view.data
  return (
    <section className="card stack" aria-labelledby={`${id}-h`}>
      <div className="hrow">
        <h2 id={`${id}-h`}>Station management</h2>
        <Help topic={HELP.toolsStations} />
        <span className="spacer" />
        <button className="btn" type="button" disabled={view.isFetching} onClick={() => void view.refetch()}>
          Refresh
        </button>
      </div>
      {view.error && <div className="note x">{errorText(view.error)}</div>}
      {view.isPending && <div className="muted">Reading the stations…</div>}
      {data && data.aps.length === 0 && <div className="muted">No SSID is on air on this router.</div>}
      {data?.aps.map((ap) => <ApSection key={ap.ifname} routerId={routerId} ap={ap} candidates={data.candidates} />)}
      {data?.notes.map((n) => (
        <div key={n} className="note">
          {n}
        </div>
      ))}
    </section>
  )
}
