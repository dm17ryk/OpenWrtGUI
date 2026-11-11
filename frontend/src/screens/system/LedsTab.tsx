import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch } from '../../api/client'
import type { LedRow, LedState } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

/** One LED action as the screen edits it: numbers and masks as typed, `label` names it in the page. */
type Draft = {
  label: string
  section: string | null
  name: string
  sysfs: string
  trigger: string
  default: boolean | null
  delayon: string
  delayoff: string
  inverted: boolean | null
  dev: string
  mode: string[]
  port_mask: string
  speed_mask: string
}

const draftOf = (r: LedRow): Draft => ({
  label: r.section ?? r.name,
  section: r.section,
  name: r.name,
  sysfs: r.sysfs,
  trigger: r.trigger,
  default: r.default ?? null,
  delayon: r.delayon != null ? String(r.delayon) : '',
  delayoff: r.delayoff != null ? String(r.delayoff) : '',
  inverted: r.inverted ?? null,
  dev: r.dev ?? '',
  mode: r.mode,
  port_mask: r.port_mask ?? '',
  speed_mask: r.speed_mask ?? '',
})

const text = (value: string): string | null => value.trim() || null
const count = (value: string): number | null => (value.trim() ? Number(value) : null)

/** The row the router gets: only the options its trigger takes, the rest null (led_ops deletes them). */
function rowOf(d: Draft, options: Record<string, string[]>): LedRow {
  const takes = new Set(options[d.trigger] ?? [])
  const only = <T,>(option: string, value: T): T | null => (takes.has(option) ? value : null)
  return {
    section: d.section,
    name: d.name.trim(),
    sysfs: d.sysfs,
    trigger: d.trigger,
    default: only('default', d.default),
    delayon: only('delayon', count(d.delayon)),
    delayoff: only('delayoff', count(d.delayoff)),
    inverted: only('inverted', d.inverted),
    dev: only('dev', text(d.dev)),
    mode: takes.has('mode') ? d.mode : [],
    port_mask: only('port_mask', text(d.port_mask)),
    speed_mask: only('speed_mask', text(d.speed_mask)),
  }
}

type RowProps = { draft: Draft; state: LedState; set: (patch: Partial<Draft>) => void; onRemove: () => void }

/** The inputs the row's trigger takes (LuCI's led-trigger plugins), named after the row. */
function TriggerOptions({ draft, state, set }: Omit<RowProps, 'onRemove'>) {
  const takes = state.trigger_options[draft.trigger] ?? []
  const of = (what: string): string => `${what} of ${draft.label}`
  return (
    <div className="row" style={{ gap: 10 }}>
      {takes.includes('default') && (
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" aria-label={`On by default ${draft.label}`} checked={draft.default ?? false} onChange={(e) => set({ default: e.target.checked })} />
          On
        </label>
      )}
      {takes.includes('delayon') && <input className="in mono" style={{ width: 110 }} inputMode="numeric" aria-label={of('On time (ms)')} placeholder="on, ms" value={draft.delayon} onChange={(e) => set({ delayon: e.target.value })} />}
      {takes.includes('delayoff') && <input className="in mono" style={{ width: 110 }} inputMode="numeric" aria-label={of('Off time (ms)')} placeholder="off, ms" value={draft.delayoff} onChange={(e) => set({ delayoff: e.target.value })} />}
      {takes.includes('inverted') && (
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" checked={draft.inverted ?? false} onChange={(e) => set({ inverted: e.target.checked })} />
          Inverted
        </label>
      )}
      {takes.includes('dev') && (
        <select className="in" aria-label={of('Device')} value={draft.dev} onChange={(e) => set({ dev: e.target.value })}>
          <option value="">(no device)</option>
          {state.devices.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
      )}
      {takes.includes('mode') &&
        state.netdev_modes.map((m) => (
          <label key={m} className="row" style={{ gap: 4 }}>
            <input
              type="checkbox"
              aria-label={`${m} on ${draft.label}`}
              checked={draft.mode.includes(m)}
              onChange={(e) => set({ mode: e.target.checked ? [...draft.mode, m] : draft.mode.filter((x) => x !== m) })}
            />
            {m}
          </label>
        ))}
      {takes.includes('port_mask') && <input className="in mono" style={{ width: 90 }} aria-label={of('Port mask')} placeholder="0x0f" value={draft.port_mask} onChange={(e) => set({ port_mask: e.target.value })} />}
      {takes.includes('speed_mask') && <input className="in mono" style={{ width: 90 }} aria-label={of('Speed mask')} placeholder="speed" value={draft.speed_mask} onChange={(e) => set({ speed_mask: e.target.value })} />}
    </div>
  )
}

function LedActionRow({ draft, state, set, onRemove }: RowProps) {
  const led = state.leds.find((l) => l.sysfs === draft.sysfs)
  const triggers = led ? [...led.triggers] : []
  if (!triggers.includes(draft.trigger)) triggers.push(draft.trigger)
  return (
    <tr>
      <td className="mono">{draft.label}</td>
      <td>
        <input className="in" style={{ width: 120 }} aria-label={`Name of ${draft.label}`} value={draft.name} onChange={(e) => set({ name: e.target.value })} />
      </td>
      <td>
        <select className="in" aria-label={`LED of ${draft.label}`} value={draft.sysfs} onChange={(e) => set({ sysfs: e.target.value })}>
          {!led && <option value={draft.sysfs}>{draft.sysfs}</option>}
          {state.leds.map((l) => (
            <option key={l.sysfs} value={l.sysfs}>
              {l.sysfs}
            </option>
          ))}
        </select>
        {led && <div className="muted">now: {led.active ?? 'none'}, {led.brightness > 0 ? 'on' : 'off'}</div>}
      </td>
      <td>
        <select className="in" aria-label={`Trigger of ${draft.label}`} value={draft.trigger} onChange={(e) => set({ trigger: e.target.value })}>
          {triggers.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </td>
      <td>
        <TriggerOptions draft={draft} state={state} set={set} />
      </td>
      <td>
        <button type="button" className="btn" aria-label={`Remove ${draft.label}`} onClick={onRemove}>
          Remove
        </button>
      </td>
    </tr>
  )
}

function LedForm({ routerId, short, state }: { routerId: string; short: string; state: LedState }) {
  const client = useQueryClient()
  const [seen, setSeen] = useState(state.rows)
  const [drafts, setDrafts] = useState<Draft[]>(() => state.rows.map(draftOf))
  const [added, setAdded] = useState(0)
  if (seen !== state.rows) {
    // the router's LED actions changed (an apply, a read again): start from them
    setSeen(state.rows)
    setDrafts(state.rows.map(draftOf))
  }
  const rows = drafts.map((d) => rowOf(d, state.trigger_options))
  const now = state.rows.map((r) => rowOf(draftOf(r), state.trigger_options))
  const body = JSON.stringify(rows) === JSON.stringify(now) ? null : { rows }
  const change = usePlanApply(`/api/routers/${routerId}/system/leds`, body, () => {
    void client.invalidateQueries({ queryKey: ['system-leds', routerId] })
  })
  const set = (label: string, patch: Partial<Draft>): void => setDrafts(drafts.map((d) => (d.label === label ? { ...d, ...patch } : d)))
  const add = (): void => {
    const label = `new ${added + 1}`
    setAdded(added + 1)
    const blank: LedRow = { section: null, name: '', sysfs: state.leds[0]?.sysfs ?? '', trigger: 'none', mode: [] }
    setDrafts([...drafts, { ...draftOf(blank), label }])
  }
  return (
    <>
      {drafts.length === 0 && <div className="muted">{short} has no LED actions: each LED keeps its default trigger.</div>}
      {drafts.length > 0 && (
        <div className="scroll-x">
          <table className="tbl" aria-label="LED actions">
            <thead>
              <tr>
                <th>Action</th>
                <th>Name</th>
                <th>LED</th>
                <th>Trigger</th>
                <th>Options</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {drafts.map((d) => (
                <LedActionRow key={d.label} draft={d} state={state} set={(patch) => set(d.label, patch)} onRemove={() => setDrafts(drafts.filter((x) => x.label !== d.label))} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="row">
        <button type="button" className="btn" disabled={state.leds.length === 0} onClick={add}>
          Add LED action
        </button>
      </div>
      <NetChange change={change} short={short} helpTopic={HELP.systemLeds} show={body !== null} />
    </>
  )
}

type Props = { routerId: string; routerName: string }

/** LuCI's LED Configuration page (D9): the `led` sections /etc/init.d/led applies at boot and at Apply. */
export function LedsTab({ routerId, routerName }: Props) {
  const short = routerName.split(' · ')[0] || routerId
  const leds = useQuery({ queryKey: ['system-leds', routerId], queryFn: () => apiFetch<LedState>(`/api/routers/${routerId}/system/leds`) })
  return (
    <section className="card stack" aria-labelledby="system-leds-h">
      <div className="hrow">
        <h2 id="system-leds-h">LEDs</h2>
        <Help topic={HELP.systemLeds} />
      </div>
      {leds.error && <div className="note x">{leds.error instanceof ApiError ? leds.error.detail : leds.error.message}</div>}
      {leds.isPending && <div className="muted">Reading the LEDs…</div>}
      {leds.data && leds.data.missing.length > 0 && <div className="note w">No answer from the router for: {leds.data.missing.join(', ')}</div>}
      {leds.data && <LedForm routerId={routerId} short={short} state={leds.data} />}
    </section>
  )
}
