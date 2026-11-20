import { useId, useState } from 'react'
import { ApiError, postJson } from '../../api/client'
import type { SendResult, ToolPlan } from '../../api/types'
import { PreviewApply } from '../../components/PreviewApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { usePreview } from '../wifi/usePreview'
import { SessionStatus } from './SessionStatus'
import { useToolSession } from './useToolSession'

type Proto = 'tcp' | 'udp'
type ListenForm = { protocol: Proto; port: number; duration_s: number }
type SendForm = { protocol: Proto; host: string; port: number; what: 'bytes' | 'text'; count: number; text: string }

function errorText(e: unknown): string {
  return e instanceof ApiError ? e.detail : String(e)
}

/** Listen (v1.2b R5): socat on the router takes connections or datagrams; each peer's bytes and first 64. */
function Listen({ routerId }: { routerId: string }) {
  const id = useId()
  const [form, setForm] = useState<ListenForm>({ protocol: 'tcp', port: 9100, duration_s: 60 })
  const { session, start, stop, error } = useToolSession(routerId, 'listen')
  const [isStarting, setStarting] = useState(false)
  const preview = usePreview<ToolPlan>(`/api/routers/${routerId}/tools/traffic/listen/preview`, form)
  const plan = preview?.plan ?? null
  const set = (patch: Partial<ListenForm>) => setForm({ ...form, ...patch })

  async function onStart() {
    if (!plan) return
    setStarting(true)
    await start(`/api/routers/${routerId}/tools/traffic/listen/start`, { ...form, digest: plan.digest })
    setStarting(false)
  }

  return (
    <section className="stack" aria-labelledby={`${id}-h`}>
      <h3 id={`${id}-h`}>Listen</h3>
      <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
        <label htmlFor={`${id}-proto`}>Protocol</label>
        <select id={`${id}-proto`} value={form.protocol} onChange={(e) => set({ protocol: e.target.value as Proto })}>
          <option value="tcp">TCP</option>
          <option value="udp">UDP</option>
        </select>
        <label htmlFor={`${id}-port`}>Port</label>
        <input id={`${id}-port`} type="number" min={1} max={65535} value={form.port} onChange={(e) => set({ port: Number(e.target.value) })} />
        <label htmlFor={`${id}-dur`}>Duration (s)</label>
        <input id={`${id}-dur`} type="number" min={10} max={300} value={form.duration_s} onChange={(e) => set({ duration_s: Number(e.target.value) })} />
      </div>
      <PreviewApply
        heading="Preview"
        lines={plan?.lines ?? []}
        warnings={plan?.warnings ?? []}
        error={preview?.error ?? null}
        isBusy={isStarting}
        isDisabled={session?.running ?? false}
        applyLabel="Start"
        onApply={() => void onStart()}
        helpTopic={HELP.toolsTraffic}
      />
      {error && (
        <div className="note x" role="alert">
          {error}
        </div>
      )}
      {session && (
        <SessionStatus session={session} onStop={() => void stop()}>
          {session.peers.length > 0 ? (
            <div className="scroll-x">
              <table className="tbl" aria-label="Peers">
                <thead>
                  <tr>
                    <th>Peer</th>
                    <th>Bytes</th>
                    <th>First bytes (hex)</th>
                  </tr>
                </thead>
                <tbody>
                  {session.peers.map((p) => (
                    <tr key={`${p.address}:${p.port}`}>
                      <td className="mono">{`${p.address}:${p.port}`}</td>
                      <td className="mono">{p.bytes}</td>
                      <td className="mono">{p.first_hex}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="muted">No peer yet.</div>
          )}
        </SessionStatus>
      )}
    </section>
  )
}

function sendBody(f: SendForm): SendForm | null {
  return f.host.trim() ? { ...f, host: f.host.trim() } : null
}

/** Send (v1.2b R6): zeros or one line of text to a host and port, at most 30 s. */
function Send({ routerId }: { routerId: string }) {
  const id = useId()
  const [form, setForm] = useState<SendForm>({ protocol: 'tcp', host: '', port: 9101, what: 'bytes', count: 1000, text: '' })
  const [result, setResult] = useState<SendResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isSending, setSending] = useState(false)
  const request = sendBody(form)
  const preview = usePreview<ToolPlan>(`/api/routers/${routerId}/tools/traffic/send/preview`, request)
  const plan = preview?.plan ?? null
  const set = (patch: Partial<SendForm>) => setForm({ ...form, ...patch })

  async function onSend() {
    if (!plan || !request) return
    setSending(true)
    setError(null)
    setResult(null)
    try {
      setResult(await postJson<SendResult>(`/api/routers/${routerId}/tools/traffic/send/apply`, { ...request, digest: plan.digest }))
    } catch (e) {
      setError(errorText(e))
    }
    setSending(false)
  }

  return (
    <section className="stack" aria-labelledby={`${id}-h`}>
      <h3 id={`${id}-h`}>Send</h3>
      <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
        <label htmlFor={`${id}-proto`}>Protocol</label>
        <select id={`${id}-proto`} value={form.protocol} onChange={(e) => set({ protocol: e.target.value as Proto })}>
          <option value="tcp">TCP</option>
          <option value="udp">UDP</option>
        </select>
        <label htmlFor={`${id}-host`}>Host</label>
        <input id={`${id}-host`} value={form.host} placeholder="192.168.1.10" onChange={(e) => set({ host: e.target.value })} />
        <label htmlFor={`${id}-port`}>Port</label>
        <input id={`${id}-port`} type="number" min={1} max={65535} value={form.port} onChange={(e) => set({ port: Number(e.target.value) })} />
      </div>
      <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
        <label htmlFor={`${id}-what`}>What</label>
        <select id={`${id}-what`} value={form.what} onChange={(e) => set({ what: e.target.value as SendForm['what'] })}>
          <option value="bytes">Bytes (zeros)</option>
          <option value="text">A line of text</option>
        </select>
        {form.what === 'bytes' ? (
          <>
            <label htmlFor={`${id}-count`}>Count</label>
            <input id={`${id}-count`} type="number" min={1} max={10000000} value={form.count} onChange={(e) => set({ count: Number(e.target.value) })} />
          </>
        ) : (
          <>
            <label htmlFor={`${id}-text`}>Text</label>
            <input id={`${id}-text`} value={form.text} maxLength={200} onChange={(e) => set({ text: e.target.value })} />
          </>
        )}
      </div>
      <PreviewApply
        heading="Preview"
        lines={plan?.lines ?? []}
        warnings={plan?.warnings ?? []}
        error={preview?.error ?? null}
        isBusy={isSending}
        applyLabel="Send"
        onApply={() => void onSend()}
        helpTopic={HELP.toolsTraffic}
      />
      {error && (
        <div className="note x" role="alert">
          {error}
        </div>
      )}
      {result &&
        (result.ok ? (
          <div className="note ok">{result.detail}</div>
        ) : (
          <div className="note x" role="alert">
            {result.detail}
          </div>
        ))}
    </section>
  )
}

/** Traffic generator (v1.2b R5, R6): socat on the router listens, or sends. */
export function TrafficTab({ routerId }: { routerId: string }) {
  const id = useId()
  return (
    <section className="card stack" aria-labelledby={`${id}-h`}>
      <div className="hrow">
        <h2 id={`${id}-h`}>Traffic generator</h2>
        <Help topic={HELP.toolsTraffic} />
      </div>
      <Listen routerId={routerId} />
      <Send routerId={routerId} />
    </section>
  )
}
