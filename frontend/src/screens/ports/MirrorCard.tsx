import { useState } from 'react'
import type { MirrorIn, PortsState, WifiMirror } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

type Flags = [boolean, boolean] // RX, TX
type Draft = { monitor: number | null; sources: Record<number, Flags> }

const OFF: Flags = [false, false]

function draftOf(state: PortsState): Draft {
  return { monitor: state.mirror.monitor, sources: { ...(state.mirror.sources ?? {}) } }
}

function wifiMirrorText(w: WifiMirror): string {
  if (!w.present) return 'not on this router'
  return w.running ? 'present · running' : 'stopped'
}

/** The request for the ports in panel order; null when it is what the router has. */
function mirrorRequest(state: PortsState, d: Draft): MirrorIn | null {
  const sources = state.ports.flatMap((p) => {
    const [rx, tx] = d.sources[p.num] ?? OFF
    return rx || tx ? [{ port: p.num, rx, tx }] : []
  })
  const was = draftOf(state)
  const same = d.monitor === was.monitor && state.ports.every((p) => JSON.stringify(d.sources[p.num] ?? OFF) === JSON.stringify(was.sources[p.num] ?? OFF))
  return same ? null : { monitor: d.monitor, sources }
}

type Props = { routerId: string; short: string; state: PortsState; onApplied: () => void }

/** The switch's port mirror (monitor port, RX/TX sources) and whether the router has the Wi-Fi mirror service. */
export function MirrorCard({ routerId, short, state, onApplied }: Props) {
  const [edited, setEdited] = useState<Draft | null>(null)
  const draft = edited ?? draftOf(state)
  const body = mirrorRequest(state, draft)
  const change = usePlanApply(`/api/routers/${routerId}/ports/mirror`, body, () => {
    setEdited(null)
    onApplied()
  })
  const setFlag = (port: number, which: 0 | 1, on: boolean): void => {
    const flags: Flags = [...(draft.sources[port] ?? OFF)]
    flags[which] = on
    setEdited({ ...draft, sources: { ...draft.sources, [port]: flags } })
  }
  return (
    <section className="card stack" aria-labelledby="mirror-h">
      <h2 id="mirror-h">Mirroring</h2>
      <div className="hrow">
        <h3>Switch port mirror</h3>
        <Help topic={HELP.portsMirror} />
      </div>
      {state.mirror.available ? (
        <>
          <label className="field">
            <span>Monitor port</span>
            <select
              className="in"
              aria-label="Monitor port"
              value={draft.monitor === null ? '' : String(draft.monitor)}
              onChange={(e) => setEdited({ ...draft, monitor: e.target.value === '' ? null : Number(e.target.value) })}
            >
              <option value="">off</option>
              {state.ports.map((p) => (
                <option key={p.num} value={String(p.num)}>
                  {p.label} · port {p.num}
                </option>
              ))}
            </select>
          </label>
          <div className="scroll-x">
            <table className="tbl" aria-label="Mirror sources">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>RX</th>
                  <th>TX</th>
                </tr>
              </thead>
              <tbody>
                {state.ports.map((p) => {
                  const [rx, tx] = draft.sources[p.num] ?? OFF
                  return (
                    <tr key={p.num}>
                      <td>{p.label}</td>
                      <td>
                        <input type="checkbox" aria-label={`${p.label} RX`} checked={rx} onChange={(e) => setFlag(p.num, 0, e.target.checked)} />
                      </td>
                      <td>
                        <input type="checkbox" aria-label={`${p.label} TX`} checked={tx} onChange={(e) => setFlag(p.num, 1, e.target.checked)} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div className="muted">
            The PC on the monitor port sees copies of the sources&apos; frames: capture with its network card in promiscuous mode (Wireshark&apos;s default).
          </div>
          <NetChange change={change} short={short} helpTopic={HELP.portsMirror} show={body !== null} />
        </>
      ) : (
        <div className="muted">This switch has no port mirroring.</div>
      )}
      <div className="hrow">
        <h3>Wi-Fi mirror</h3>
        <Help topic={HELP.portsWifiMirror} />
      </div>
      <div className="row">
        <span className={state.wifi_mirror.running ? 'b air' : 'b neu'}>{wifiMirrorText(state.wifi_mirror)}</span>
        <span className="muted">Start, stop and restart: Discovery › Programs and services. Excluded MACs and the iperf warning are not built yet.</span>
      </div>
    </section>
  )
}
