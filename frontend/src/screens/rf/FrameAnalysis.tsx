import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch, postJson } from '../../api/client'
import type { Direction, FramePlanOut, FrameState, FrameWindow } from '../../api/types'
import { PreviewApply } from '../../components/PreviewApply'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'

type Props = { routerId: string; radio: string; live: FrameState | null; retryPct: number | null }

const pct = (part: number, whole: number): string => (whole > 0 ? `${((100 * part) / whole).toFixed(1)} %` : '—')

function rateLabel(rate: string): string {
  return rate.startsWith('MCS') ? rate : `${rate} Mb/s`
}

/** One direction's rate mix as bars, most used first. */
function RateMix({ d, label, tone }: { d: Direction; label: string; tone: 'rx' | 'tx' }) {
  const total = d.frames ?? 0
  const rows = Object.entries(d.rates ?? {}).sort((a, b) => b[1] - a[1])
  if (rows.length === 0) return <div className="muted">no frames in this window</div>
  return (
    <ul className="mix" aria-label={label}>
      {rows.map(([rate, n]) => (
        <li key={rate} className="row" style={{ gap: 8 }}>
          <span className="mono" style={{ minWidth: 92 }}>
            {rateLabel(rate)}
          </span>
          <span className="bar" style={{ flex: '1 1 120px' }}>
            <span style={{ width: `${total > 0 ? (100 * n) / total : 0}%`, background: `var(--${tone})` }} />
          </span>
          <span className="mono muted">
            {n} ({pct(n, total)})
          </span>
        </li>
      ))}
    </ul>
  )
}

/** The RX signal histogram in 5 dB bins, strongest first. */
function SignalHist({ d, label }: { d: Direction; label: string }) {
  const rows = Object.entries(d.signal_hist ?? {})
    .map(([bin, n]) => [Number(bin), n] as const)
    .sort((a, b) => b[0] - a[0])
  if (rows.length === 0) return null
  const top = Math.max(...rows.map(([, n]) => n))
  return (
    <ul className="mix" aria-label={label}>
      {rows.map(([bin, n]) => (
        <li key={bin} className="row" style={{ gap: 8 }}>
          <span className="mono" style={{ minWidth: 92 }}>
            {bin} … {bin + 4} dBm
          </span>
          <span className="bar" style={{ flex: '1 1 120px' }}>
            <span style={{ width: `${(100 * n) / top}%`, background: 'var(--rx)' }} />
          </span>
          <span className="mono muted">{n}</span>
        </li>
      ))}
    </ul>
  )
}

function WindowView({ w, title, fcs, retryPct }: { w: FrameWindow; title: string; fcs: boolean; retryPct: number | null }) {
  const which = title === 'Last window' ? 'last window' : 'since start'
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="eyebrow">
        {title} · {w.frames} frames
      </div>
      <div className="hrow">
        <span className="swatch" style={{ background: 'var(--rx)' }} />
        <strong>RX at AP</strong>
      </div>
      <RateMix d={w.rx} label={`Rate mix RX at AP, ${which}`} tone="rx" />
      <span className="muted">Retry flag RX: {pct(w.rx.retries ?? 0, w.rx.frames ?? 0)}</span>
      <SignalHist d={w.rx} label={`RX signal, ${which}`} />
      <div className="hrow">
        <span className="swatch" style={{ background: 'var(--tx)' }} />
        <strong>TX from AP</strong>
      </div>
      <RateMix d={w.tx} label={`Rate mix TX from AP, ${which}`} tone="tx" />
      <span className="muted">
        Retry flag TX: {pct(w.tx.retries ?? 0, w.tx.frames ?? 0)}
        {retryPct !== null && ` · TX retries from the station counters: ${retryPct.toFixed(1)} %`}
      </span>
      <span className="muted">{fcs ? `Bad FCS: ${pct(w.bad_fcs, w.frames)} of ${w.frames} frames` : 'Bad FCS: not reported by this radio'}</span>
      {w.dropped !== null && w.dropped > 0 && <span className="muted">Dropped by the router's kernel: {w.dropped}</span>}
    </div>
  )
}

function minutesLeft(until: string | null): string {
  if (!until) return ''
  const m = Math.max(0, Math.ceil((new Date(until).getTime() - Date.now()) / 60000))
  return ` · ${m} min left`
}

/** Frame analysis (spec 7.3, plan D12): off by default, short tcpdump windows on the monitor interface. */
export function FrameAnalysis({ routerId, radio, live, retryPct }: Props) {
  const client = useQueryClient()
  const base = `/api/routers/${routerId}/rf/${radio}/frames`
  const fetched = useQuery({ queryKey: ['frames', routerId, radio], queryFn: () => apiFetch<FrameState>(base) })
  const [plan, setPlan] = useState<FramePlanOut | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const state = live ?? fetched.data ?? null

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
  const ask = (): Promise<void> => act(async () => setPlan(await postJson<FramePlanOut>(`${base}/preview`)))
  const start = (): Promise<void> =>
    act(async () => {
      if (!plan) return
      client.setQueryData(['frames', routerId, radio], await postJson<FrameState>(`${base}/start`, { digest: plan.digest }))
      setPlan(null)
    })
  const stop = (): Promise<void> =>
    act(async () => {
      client.setQueryData(['frames', routerId, radio], await postJson<FrameState>(`${base}/stop`))
    })

  return (
    <section className="card stack" aria-labelledby="frames-h">
      <div className="hrow">
        <h2 id="frames-h">Frame analysis</h2>
        <Help topic={HELP.rfFrames} />
      </div>
      {state?.running ? (
        <>
          <div className="row">
            <span className="b air">
              window {state.windows ?? 0} · 3 s of every 5 s{minutesLeft(state.ends_at ?? null)}
            </span>
            <HelpTip topic={HELP.rfFrames}>
              <button className="btn" type="button" disabled={busy} onClick={() => void stop()}>
                Stop frame analysis
              </button>
            </HelpTip>
          </div>
          {state.note && <div className="note">{state.note}</div>}
          <div className="rf-cols">
            {state.last ? <WindowView w={state.last} title="Last window" fcs={state.fcs_reported ?? true} retryPct={retryPct} /> : <div className="muted">Waiting for the first window…</div>}
            {state.totals && <WindowView w={state.totals} title="Since start" fcs={state.fcs_reported ?? true} retryPct={retryPct} />}
          </div>
        </>
      ) : (
        <>
          <span className="muted">
            Off. It adds a monitor interface on the radio and reads what it hears: the rate mix per direction, the RX signal, the retry
            flag and frames with a bad FCS. It costs router CPU.
          </span>
          {state?.error && <div className="note w">Stopped: {state.error}</div>}
          {!plan && (
            <div className="row">
              <button className="btn" type="button" disabled={busy} onClick={() => void ask()}>
                Frame analysis…
              </button>
            </div>
          )}
          {plan && (
            <PreviewApply
              heading="Commands that will run"
              lines={plan.lines}
              warnings={plan.warnings}
              error={error}
              isBusy={busy}
              applyLabel="Start frame analysis"
              onApply={() => void start()}
              helpTopic={HELP.rfFrames}
            />
          )}
          {!plan && error && (
            <div className="note x" role="alert">
              {error}
            </div>
          )}
        </>
      )}
    </section>
  )
}
