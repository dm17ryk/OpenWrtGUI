import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { ApiError, apiFetch, postJson } from '../../api/client'
import type { Advance, ApplyResult, GuardOut, Mode, RadioState, Station, StepJob, StepPlanOut } from '../../api/types'
import { PreviewApply } from '../../components/PreviewApply'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import { MODE_LABEL, MODES } from './draft'
import { StepResults } from './StepResults'
import { TickRow } from './TickRow'
import { usePreview } from './usePreview'
import { isRunning, usePendingRestores, useStepJob, WAITING } from './useStepJob'

const SHOWN_STEPS = 5
const ADVANCES: ReadonlyArray<readonly [Advance, string]> = [
  ['timer', 'Timer'],
  ['manual', 'Manual'],
  ['rejoin', 'Station re-joins'],
]

type Props = { routerId: string; short: string; radio: RadioState; onEnded: () => void }

function stepText(mode: Mode, channel: number, dbm: number | null | undefined): string {
  return `${MODE_LABEL[mode]} · channel ${channel}${dbm === null || dbm === undefined ? '' : ` · ${dbm} dBm`}`
}

function minutes(seconds: number): string {
  return seconds < 90 ? `${Math.max(1, Math.round(seconds / 60))} min` : `${Math.round(seconds / 60)} min`
}

function left(until: string | null): string {
  if (!until) return ''
  const s = Math.max(0, Math.round((new Date(until).getTime() - Date.now()) / 1000))
  return s >= 60 ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}` : `${s} s`
}

/** What the running step-through is doing, in one line (plan D5). */
function runningText(job: StepJob): string {
  if (job.phase === 'restoring') return `Restoring ${job.radio}…`
  const step = job.current ? ` · ${stepText(job.current.mode, job.current.channel, job.current.txpower_dbm)}` : ''
  const head = `Step ${job.index} of ${job.total}${step}`
  if (job.phase === 'dwell') return `${head} · dwell ${left(job.phase_ends_at)} left`
  if (job.phase === 'waiting for station') return `${head} · waiting for ${job.station ?? 'the station'} (${left(job.phase_ends_at)} left)`
  if (job.phase === 'waiting for Next') return `${head} · waiting for Next`
  return `${head} · applying and proving on air`
}

function endedText(job: StepJob): string {
  if (job.phase === 'done') return `Done: ${job.results.length} steps, ${job.radio} restored`
  if (job.phase === 'stopped') return job.restore_pending ? `Stopped after step ${job.index}` : `Stopped after step ${job.index}, ${job.radio} restored`
  return `Failed at step ${job.index}`
}

/** The planned commands, step by step, then the restore (plan D3); from step 6 on behind "Show all". */
function previewLines(plan: StepPlanOut, all: boolean): string[] {
  const out: string[] = []
  const steps = all ? plan.steps : plan.steps.slice(0, SHOWN_STEPS)
  steps.forEach((s, i) => {
    out.push(`# Step ${s.index} · ${stepText(s.mode, s.channel, s.txpower_dbm)}`, ...(plan.step_lines[i] ?? []))
  })
  if (!all && plan.steps.length > SHOWN_STEPS) out.push(`# … ${plan.steps.length - SHOWN_STEPS} more steps`)
  out.push('# Restore at the end', ...plan.restore_lines)
  return out
}

/** Wi-Fi step-through (spec 7.2): every ticked mode × channel × TX power, each step proven on air. */
export function StepThroughCard({ routerId, short, radio, onEnded }: Props) {
  const client = useQueryClient()
  const [modes, setModes] = useState<Mode[]>([])
  const [channels, setChannels] = useState<number[]>([])
  const [powers, setPowers] = useState<number[]>([])
  const [advance, setAdvance] = useState<Advance>('timer')
  const [dwell, setDwell] = useState('60')
  const [station, setStation] = useState('')
  const [rejoinLimit, setRejoinLimit] = useState('120')
  const [all, setAll] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const job = useStepJob(routerId)
  const pending = usePendingRestores()
  const guard = useQuery({ queryKey: ['guard'], queryFn: () => apiFetch<GuardOut>('/api/guard') })
  const stations = useQuery({
    queryKey: ['stations', routerId],
    queryFn: () => apiFetch<Station[]>(`/api/routers/${routerId}/wifi/stations`),
    enabled: advance === 'rejoin',
  })

  const body =
    modes.length === 0 && channels.length === 0
      ? null
      : {
          radio: radio.name,
          modes: MODES.filter((m) => modes.includes(m)),
          channels: [...channels].sort((a, b) => a - b),
          powers: [...powers].sort((a, b) => a - b),
          advance,
          dwell_s: Number(dwell),
          station: advance === 'rejoin' ? station.trim() || null : null,
          rejoin_limit_s: Number(rejoinLimit),
        }
  const preview = usePreview<StepPlanOut>(`/api/routers/${routerId}/wifi/step-through/preview`, body)
  const plan = preview?.plan ?? null
  const current = job.data ?? null
  const running = isRunning(current)
  const live = guard.data?.live ?? false
  const leftBehind = (pending.data ?? []).find((p) => p.router_id === routerId && p.radio === radio.name)
  const endedPhase = current && !running ? current.phase : null
  useEffect(() => {
    // a run that ended changed the radio (restored, or left at a step): the screen reads it again, once per
    // phase change; onEnded is a new function on every render of the screen, so it is not a dependency
    if (endedPhase !== null) onEnded()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endedPhase])

  const refresh = (): void => {
    void client.invalidateQueries({ queryKey: ['step-through', routerId] })
    void client.invalidateQueries({ queryKey: ['step-pending'] })
  }
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
  const start = (): Promise<void> =>
    act(async () => {
      if (!body || !plan) return
      const started = await postJson<StepJob>(`/api/routers/${routerId}/wifi/step-through/start`, { ...body, digest: plan.digest })
      client.setQueryData(['step-through', routerId], started)
    })
  const post = (what: 'next' | 'stop'): Promise<void> =>
    act(async () => {
      client.setQueryData(['step-through', routerId], await postJson<StepJob>(`/api/routers/${routerId}/wifi/step-through/${what}`))
    })
  const restore = (): Promise<void> =>
    act(async () => {
      await postJson<ApplyResult>(`/api/routers/${routerId}/wifi/step-through/restore`, { radio: radio.name })
      refresh()
      onEnded()
    })

  return (
    <section className="card stack" aria-labelledby="step-h">
      <div className="hrow">
        <h2 id="step-h">Step-through</h2>
        <Help topic={HELP.wifiStep} />
      </div>
      {leftBehind && !running && (
        <div className="note w row">
          <span>{radio.name} was left at a step by a step-through that did not restore it.</span>
          <HelpTip topic={HELP.wifiStep}>
            <button className="btn" type="button" disabled={busy || live} onClick={() => void restore()}>
              Restore {radio.name}
            </button>
          </HelpTip>
        </div>
      )}
      {current && running && (
        <div className="stack" style={{ gap: 8 }}>
          <div role="status" className="b air">
            {runningText(current)}
          </div>
          <div className="row">
            <button className="btn" type="button" disabled={busy || !WAITING.includes(current.phase)} onClick={() => void post('next')}>
              Next step
            </button>
            <button className="btn" type="button" disabled={busy || current.phase === 'restoring'} onClick={() => void post('stop')}>
              Stop and restore
            </button>
          </div>
        </div>
      )}
      {current && !running && (
        <div role="status" className={current.phase === 'done' ? 'b air' : 'b park'}>
          {endedText(current)}
        </div>
      )}
      {current?.error && <div className="note x">{current.error}</div>}
      {!running && (
        <>
          <div className="muted">
            Each step puts one pure mode on one channel (and one TX power, if ticked) on air through Apply, proves it, then waits. The
            radio is put back as it was at the end.
          </div>
          <TickRow label="Modes" values={MODES} picked={modes} onChange={setModes} text={(m) => MODE_LABEL[m]} name={(m) => `Step mode ${m}`} />
          <TickRow label="Channels" values={radio.limits.channels} picked={channels} onChange={setChannels} text={String} name={(c) => `Step channel ${c}`} />
          <TickRow label="TX power (none ticked: as it is)" values={radio.limits.txpower_dbm} picked={powers} onChange={setPowers} text={String} name={(p) => `Step power ${p} dBm`} />
          <div className="row">
            <div className="seg" role="group" aria-label="Advance">
              {ADVANCES.map(([value, label]) => (
                <button key={value} type="button" className={advance === value ? 'on' : ''} aria-pressed={advance === value} onClick={() => setAdvance(value)}>
                  {label}
                </button>
              ))}
            </div>
            {advance !== 'manual' && (
              <div className="field">
                <label htmlFor="step-dwell">Dwell (s)</label>
                <input id="step-dwell" className="in" inputMode="numeric" value={dwell} onChange={(e) => setDwell(e.target.value)} />
              </div>
            )}
          </div>
          {advance === 'rejoin' && (
            <div className="grid">
              <div className="field">
                <label htmlFor="step-station">Station that re-joins</label>
                <input id="step-station" className="in mono" list="step-stations" value={station} placeholder="aa:bb:cc:dd:ee:ff" onChange={(e) => setStation(e.target.value)} />
                <datalist id="step-stations">
                  {(stations.data ?? []).map((s) => (
                    <option key={s.mac} value={s.mac}>
                      {s.name ?? s.mac}
                    </option>
                  ))}
                </datalist>
              </div>
              <div className="field">
                <label htmlFor="step-limit">Re-join limit (s)</label>
                <input id="step-limit" className="in" inputMode="numeric" value={rejoinLimit} onChange={(e) => setRejoinLimit(e.target.value)} />
              </div>
            </div>
          )}
          {live && <div className="note w">Bench Guard: {guard.data?.reasons[0]?.text ?? 'a harness run is live'}. A step-through waits until it ends.</div>}
          {plan && plan.steps.length > SHOWN_STEPS && (
            <button className="btn" type="button" onClick={() => setAll(!all)}>
              {all ? 'Show the first steps only' : `Show all ${plan.steps.length} steps`}
            </button>
          )}
          <PreviewApply
            heading={plan ? `Step-through preview: ${plan.steps.length} steps, about ${minutes(plan.estimate_s)}` : `Step-through on ${short}`}
            lines={plan ? previewLines(plan, all) : []}
            warnings={plan?.warnings ?? []}
            error={error ?? preview?.error ?? null}
            isBusy={busy}
            isDisabled={live || (plan?.warnings.length ?? 0) > 0}
            applyLabel="Start step-through"
            onApply={() => void start()}
            helpTopic={HELP.wifiStep}
          />
        </>
      )}
      {current && <StepResults results={current.results} csvPath={current.csv_path} />}
    </section>
  )
}
