import { useId, useState } from 'react'
import type { ToolPlan, ToolSessionView } from '../../api/types'
import { PreviewApply } from '../../components/PreviewApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { usePreview } from '../wifi/usePreview'
import { SessionStatus } from './SessionStatus'
import { useToolSession } from './useToolSession'

type Form = {
  mode: 'client' | 'server'
  host: string
  port: number
  protocol: 'tcp' | 'udp'
  reverse: boolean
  duration_s: number
  udp_mbps: number
}

const START: Form = { mode: 'client', host: '', port: 5201, protocol: 'tcp', reverse: false, duration_s: 10, udp_mbps: 10 }

function body(f: Form): object | null {
  if (f.mode === 'server') return { mode: 'server', port: f.port }
  if (!f.host.trim()) return null
  return {
    mode: 'client',
    host: f.host.trim(),
    port: f.port,
    protocol: f.protocol,
    reverse: f.reverse,
    duration_s: f.duration_s,
    udp_mbps: f.udp_mbps,
  }
}

function num(v: number | null | undefined, digits = 1): string {
  return v == null ? '—' : v.toFixed(digits)
}

function summaryText(s: NonNullable<ToolSessionView['summary']>): string {
  const parts = [`Sent ${num(s.sent_mbps)} Mb/s`, `received ${num(s.received_mbps)} Mb/s`]
  if (s.jitter_ms != null) parts.push(`jitter ${num(s.jitter_ms, 2)} ms`)
  if (s.lost_pct != null) parts.push(`lost ${num(s.lost_pct)} %`)
  if (s.cpu_pct != null) parts.push(`router CPU ${Math.round(s.cpu_pct)} %`)
  return parts.join(' · ')
}

function Results({ session }: { session: ToolSessionView }) {
  const udp = session.intervals.some((i) => i.jitter_ms != null || i.lost_pct != null)
  return (
    <>
      {session.intervals.length > 0 && (
        <div className="scroll-x">
          <table className="tbl" aria-label="Throughput">
            <thead>
              <tr>
                <th>Time</th>
                <th>Mb/s</th>
                {udp ? (
                  <>
                    <th>Jitter (ms)</th>
                    <th>Lost (%)</th>
                  </>
                ) : (
                  <th>Retransmits</th>
                )}
              </tr>
            </thead>
            <tbody>
              {session.intervals.map((i) => (
                <tr key={`${i.start_s}-${i.end_s}`}>
                  <td>{`${Math.round(i.start_s)}–${Math.round(i.end_s)} s`}</td>
                  <td className="mono">{num(i.mbps)}</td>
                  {udp ? (
                    <>
                      <td className="mono">{num(i.jitter_ms, 2)}</td>
                      <td className="mono">{num(i.lost_pct)}</td>
                    </>
                  ) : (
                    <td className="mono">{i.retransmits ?? '—'}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {session.summary && <div>{summaryText(session.summary)}</div>}
    </>
  )
}

/**
 * Throughput (v1.2b R4): iperf3 on the router, as a client to a host you name or as a one-shot server for your
 * PC's iperf3. The results arrive each second while it runs.
 */
export function ThroughputTab({ routerId }: { routerId: string }) {
  const id = useId()
  const [form, setForm] = useState<Form>(START)
  const { session, start, stop, error } = useToolSession(routerId, 'throughput')
  const [isStarting, setStarting] = useState(false)
  const request = body(form)
  const preview = usePreview<ToolPlan>(`/api/routers/${routerId}/tools/throughput/preview`, request)
  const plan = preview?.plan ?? null
  const set = (patch: Partial<Form>) => setForm({ ...form, ...patch })
  const client = form.mode === 'client'

  async function onStart() {
    if (!plan || !request) return
    setStarting(true)
    await start(`/api/routers/${routerId}/tools/throughput/start`, { ...request, digest: plan.digest })
    setStarting(false)
  }

  return (
    <section className="card stack" aria-labelledby={`${id}-h`}>
      <div className="hrow">
        <h2 id={`${id}-h`}>Throughput</h2>
        <Help topic={HELP.toolsThroughput} />
      </div>
      <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
        <label htmlFor={`${id}-mode`}>The router</label>
        <select id={`${id}-mode`} value={form.mode} onChange={(e) => set({ mode: e.target.value as Form['mode'] })}>
          <option value="client">connects to a host</option>
          <option value="server">waits for a client</option>
        </select>
        {client && (
          <>
            <label htmlFor={`${id}-host`}>Host</label>
            <input id={`${id}-host`} value={form.host} placeholder="192.168.1.10" onChange={(e) => set({ host: e.target.value })} />
          </>
        )}
        <label htmlFor={`${id}-port`}>Port</label>
        <input id={`${id}-port`} type="number" min={1} max={65535} value={form.port} onChange={(e) => set({ port: Number(e.target.value) })} />
      </div>
      {client && (
        <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
          <label htmlFor={`${id}-proto`}>Protocol</label>
          <select id={`${id}-proto`} value={form.protocol} onChange={(e) => set({ protocol: e.target.value as Form['protocol'] })}>
            <option value="tcp">TCP</option>
            <option value="udp">UDP</option>
          </select>
          <label htmlFor={`${id}-dir`}>Direction</label>
          <select id={`${id}-dir`} value={form.reverse ? 'in' : 'out'} onChange={(e) => set({ reverse: e.target.value === 'in' })}>
            <option value="out">Router sends</option>
            <option value="in">Router receives</option>
          </select>
          <label htmlFor={`${id}-dur`}>Duration (s)</label>
          <input id={`${id}-dur`} type="number" min={1} max={60} value={form.duration_s} onChange={(e) => set({ duration_s: Number(e.target.value) })} />
          {form.protocol === 'udp' && (
            <>
              <label htmlFor={`${id}-rate`}>UDP rate (Mb/s)</label>
              <input id={`${id}-rate`} type="number" min={1} max={1000} value={form.udp_mbps} onChange={(e) => set({ udp_mbps: Number(e.target.value) })} />
            </>
          )}
        </div>
      )}
      <PreviewApply
        heading="Preview"
        lines={plan?.lines ?? []}
        warnings={plan?.warnings ?? []}
        error={preview?.error ?? null}
        isBusy={isStarting}
        isDisabled={session?.running ?? false}
        applyLabel="Start"
        onApply={() => void onStart()}
        helpTopic={HELP.toolsThroughput}
      />
      {error && (
        <div className="note x" role="alert">
          {error}
        </div>
      )}
      {session && (
        <SessionStatus session={session} onStop={() => void stop()}>
          <Results session={session} />
        </SessionStatus>
      )}
    </section>
  )
}
