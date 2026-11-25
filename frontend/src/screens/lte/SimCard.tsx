import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { ApiError, apiFetch, postJson } from '../../api/client'
import type { GuardOut, PinResult, SimState } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { guardReasonText } from '../../shell/guardText'

const PIN_FORMAT = /^\d{4,8}$/
const BLOCKED = 'The SIM is blocked: it needs its PUK, which the app does not offer'

function triesLeft(n: number): string {
  return `${n} ${n === 1 ? 'try' : 'tries'} left`
}

/** The one line the card opens with: what the SIM asks for. */
function statusLine(sim: SimState): string {
  switch (sim.pin) {
    case 'off':
      return 'PIN off'
    case 'needed':
      return sim.tries_left != null ? `PIN needed: ${triesLeft(sim.tries_left)}` : 'PIN needed'
    case 'entered':
      return 'PIN entered'
    case 'blocked':
      return sim.note ?? BLOCKED
    default:
      return 'The SIM state is not known'
  }
}

/**
 * The SIM's PIN state and the Enter PIN form, which shows only while the SIM asks for the PIN (E3: never on the
 * last try). The PIN lives in the field only until it is sent: it is emptied at once and after every answer, and
 * never goes into the query cache or a message (Review Focus 1).
 */
export function SimCard({ routerId }: { routerId: string }) {
  const client = useQueryClient()
  const sim = useQuery({ queryKey: ['lte-sim', routerId], queryFn: () => apiFetch<SimState>(`/api/routers/${routerId}/lte/sim`) })
  const guard = useQuery({ queryKey: ['guard'], queryFn: () => apiFetch<GuardOut>('/api/guard') })
  const live = guard.data?.live ?? false
  const [pin, setPin] = useState('')
  const [answer, setAnswer] = useState<{ text: string; ok: boolean } | null>(null)
  const [isBusy, setBusy] = useState(false)
  const state = sim.data
  const runTitle = live && guard.data ? `Waits for the run: ${guardReasonText(guard.data)}` : undefined

  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault()
    if (!PIN_FORMAT.test(pin) || live || isBusy) return
    const sent = pin
    setPin('') // gone from the field before the request leaves, whatever the answer is
    setBusy(true)
    setAnswer(null)
    try {
      const result = await postJson<PinResult>(`/api/routers/${routerId}/lte/sim/pin`, { pin: sent })
      setAnswer({ text: result.message, ok: result.accepted })
    } catch (err) {
      setAnswer({ text: err instanceof ApiError ? err.detail : String(err), ok: false })
    } finally {
      setBusy(false)
      void client.invalidateQueries({ queryKey: ['lte-sim', routerId] })
    }
  }

  return (
    <section className="card stack" aria-labelledby="lte-sim-h">
      <div className="hrow">
        <h2 id="lte-sim-h">SIM</h2>
        <Help topic={HELP.lteSim} />
      </div>
      {sim.isError && (
        <div className="note x" role="alert">
          {sim.error instanceof ApiError ? sim.error.detail : String(sim.error)}
        </div>
      )}
      {state && (
        <>
          <div className="stack" style={{ gap: 2 }}>
            <span className={state.pin === 'blocked' ? 'b bad' : 'b'}>{statusLine(state)}</span>
            {state.card && <span className="muted">Card: {state.card}</span>}
          </div>
          {state.note && state.pin !== 'blocked' && <div className="note w">{state.note}</div>}
          {state.can_enter_pin && (
            <form className="row" onSubmit={(e) => void submit(e)}>
              <input
                className="in mono"
                aria-label="SIM PIN"
                type="password"
                inputMode="numeric"
                autoComplete="off"
                spellCheck={false}
                maxLength={8}
                value={pin}
                onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
              />
              <button className="btn pri" type="submit" disabled={!PIN_FORMAT.test(pin) || live || isBusy} title={runTitle}>
                Enter PIN
              </button>
            </form>
          )}
        </>
      )}
      {live && guard.data && state?.can_enter_pin && (
        <div className="note w">A harness run is live ({guardReasonText(guard.data)}): Enter PIN waits for it to end.</div>
      )}
      {answer && (
        <div className={answer.ok ? 'note' : 'note x'} role={answer.ok ? 'status' : 'alert'}>
          {answer.text}
        </div>
      )}
    </section>
  )
}
