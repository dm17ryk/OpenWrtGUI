import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch, postJson } from '../../api/client'
import type { CaptureDevices, CaptureIn, CaptureView } from '../../api/types'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'

/** Capture on a router interface to a .pcap in Documents, or straight into Wireshark (spec 7.7). */
export function CaptureCard({ routerId }: { routerId: string }) {
  const client = useQueryClient()
  const devices = useQuery({ queryKey: ['capture-devices', routerId], queryFn: () => apiFetch<CaptureDevices>(`/api/routers/${routerId}/captures/devices`) })
  const list = useQuery({
    queryKey: ['captures', routerId],
    queryFn: () => apiFetch<CaptureView[]>(`/api/routers/${routerId}/captures`),
    refetchInterval: (q) => (q.state.data?.some((c) => c.running) ? 2000 : false),
  })
  const [device, setDevice] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [duration, setDuration] = useState('60')
  const [error, setError] = useState<string | null>(null)
  const chosen = device ?? devices.data?.devices[0] ?? ''
  const refresh = (): void => void client.invalidateQueries({ queryKey: ['captures', routerId] })
  const run = async (fn: () => Promise<unknown>): Promise<void> => {
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err))
    } finally {
      refresh()
    }
  }
  const start = (output: CaptureIn['output']): Promise<void> =>
    run(() => postJson<CaptureView>(`/api/routers/${routerId}/captures`, { device: chosen, filter, duration_s: Number(duration) || 60, output }))
  const busy = list.data?.some((c) => c.running) ?? false
  return (
    <section className="card stack" aria-labelledby="capture-h">
      <div className="hrow">
        <h2 id="capture-h">Capture</h2>
        <Help topic={HELP.capture} />
      </div>
      <div className="grid">
        <label className="field">
          <span>Interface</span>
          <select className="in" value={chosen} onChange={(e) => setDevice(e.target.value)}>
            {(devices.data?.devices ?? []).map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Filter</span>
          <input className="in mono" placeholder="host 192.168.1.30 and udp" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </label>
        <label className="field">
          <span>Duration (s)</span>
          <input className="in mono" inputMode="numeric" value={duration} onChange={(e) => setDuration(e.target.value)} />
        </label>
      </div>
      <div className="row">
        {devices.data?.wireshark && (
          <HelpTip topic={HELP.capture}>
            <button className="btn pri" type="button" disabled={!chosen || busy} onClick={() => void start('wireshark')}>
              Live in Wireshark
            </button>
          </HelpTip>
        )}
        <HelpTip topic={HELP.capture}>
          <button className="btn" type="button" disabled={!chosen || busy} onClick={() => void start('file')}>
            Save .pcap
          </button>
        </HelpTip>
      </div>
      {error && (
        <div className="note x" role="alert">
          {error}
        </div>
      )}
      {(list.data ?? []).length > 0 && (
        <div className="scroll-x">
          <table className="tbl" aria-label="Captures">
            <thead>
              <tr>
                <th>Interface</th>
                <th>Filter</th>
                <th>Bytes</th>
                <th>Saved to</th>
                <th>
                  <span className="sr-only">Stop</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {(list.data ?? []).map((c) => (
                <tr key={c.id}>
                  <td className="mono">{c.device}</td>
                  <td className="mono">{c.filter || '—'}</td>
                  <td className="mono">{c.bytes}</td>
                  <td className="mono">{c.error ?? (c.output === 'wireshark' ? 'Wireshark' : (c.path ?? 'when it stops'))}</td>
                  <td>
                    {c.running && (
                      <button className="btn" type="button" onClick={() => void run(() => postJson(`/api/routers/${routerId}/captures/${c.id}/stop`))}>
                        Stop
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="muted small">
        The app&apos;s own SSH connection is never captured. mon0 is created on demand and removed afterwards, and not while a harness run is live. Files go
        to Documents\OpenWrtGUI\captures. &quot;Live in Wireshark&quot; appears only when Wireshark is installed.
      </div>
    </section>
  )
}
