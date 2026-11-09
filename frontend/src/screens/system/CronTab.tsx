import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch } from '../../api/client'
import type { CronState } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

const FIELDS = [
  ['minute', 'Minute'],
  ['hour', 'Hour'],
  ['day', 'Day'],
  ['month', 'Month'],
  ['weekday', 'Weekday'],
] as const
type Field = (typeof FIELDS)[number][0]
type Task = Record<Field, string> & { command: string }
type Row = ({ kind: 'task'; task: Task } | { kind: 'line'; text: string }) & { id: number }

let seq = 0
const nextId = (): number => {
  seq += 1
  return seq
}

const TASK = /^\s*(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s(.*)$/
const KEPT = /^\s*(#|[A-Za-z_][A-Za-z0-9_]*=|$)/ // comments, variables and blank lines stay as written

function parse(text: string): Row[] {
  const lines = text.endsWith('\n') ? text.slice(0, -1).split('\n') : text ? text.split('\n') : []
  return lines.map((line): Row => {
    const m = KEPT.test(line) ? null : TASK.exec(line)
    if (!m) return { id: nextId(), kind: 'line', text: line }
    return { id: nextId(), kind: 'task', task: { minute: m[1], hour: m[2], day: m[3], month: m[4], weekday: m[5], command: m[6] } }
  })
}

function render(rows: Row[]): string {
  const lines = rows.map((r) => (r.kind === 'line' ? r.text : `${FIELDS.map(([f]) => r.task[f]).join(' ')} ${r.task.command}`))
  return lines.length ? `${lines.join('\n')}\n` : ''
}

function cronLine(s: CronState): string {
  if (!s.cron_enabled) return 'cron is disabled: Apply enables it'
  return s.cron_running ? 'cron is enabled and running' : 'cron is enabled and idle: it starts once there is a task'
}

const NEW_TASK: Task = { minute: '*', hour: '*', day: '*', month: '*', weekday: '*', command: '' }

function CronForm({ routerId, short, state }: { routerId: string; short: string; state: CronState }) {
  const client = useQueryClient()
  const [initial, setInitial] = useState(state.text)
  const [rows, setRows] = useState<Row[]>(() => parse(state.text))
  const [raw, setRaw] = useState<string | null>(null) // the text view's own text while it is open
  const text = raw ?? render(rows)
  const body = text !== initial && (text.trim() || initial.trim()) ? { text } : null
  const change = usePlanApply(`/api/routers/${routerId}/system/crontab`, body, () => {
    setInitial(text)
    void client.invalidateQueries({ queryKey: ['system-crontab', routerId] })
  })
  const edit = (id: number, patch: Partial<Task>): void =>
    setRows(rows.map((r) => (r.id === id && r.kind === 'task' ? { ...r, task: { ...r.task, ...patch } } : r)))
  const remove = (id: number): void => setRows(rows.filter((r) => r.id !== id))
  const toggle = (): void => {
    if (raw === null) setRaw(render(rows))
    else {
      setRows(parse(raw))
      setRaw(null)
    }
  }
  // a task is named by its line in the file: the router's refusals say "line N"
  const numbers = new Map(rows.map((r, i) => [r.id, i + 1]))
  return (
    <>
      <div className="row">
        <button type="button" className="btn" onClick={toggle}>
          {raw !== null ? 'Edit as rows' : 'Edit as text'}
        </button>
        {raw === null && (
          <button type="button" className="btn" onClick={() => setRows([...rows, { id: nextId(), kind: 'task', task: NEW_TASK }])}>
            Add task
          </button>
        )}
      </div>
      {raw !== null ? (
        <label className="field">
          <span>Crontab</span>
          <textarea className="in mono" aria-label="Crontab" rows={10} spellCheck={false} value={raw} onChange={(e) => setRaw(e.target.value)} />
        </label>
      ) : (
        <div className="stack">
          {!rows.some((r) => r.kind === 'task') && <div className="muted">No scheduled tasks.</div>}
          {rows.map((r) => {
            if (r.kind === 'line') {
              return (
                <div key={r.id} className="row">
                  <span className="mono muted" style={{ flex: 1 }}>
                    {r.text || '(blank line)'}
                  </span>
                  <button type="button" className="btn" onClick={() => remove(r.id)}>
                    Remove
                  </button>
                </div>
              )
            }
            return (
              <div key={r.id} className="row" role="group" aria-label={`Line ${numbers.get(r.id) ?? ''}`}>
                <span className="mono muted" style={{ alignSelf: 'flex-end', paddingBottom: 10 }}>
                  {numbers.get(r.id)}
                </span>
                {FIELDS.map(([f, label]) => (
                  <label key={f} className="field" style={{ width: 84 }}>
                    <span>{label}</span>
                    <input className="in mono" aria-label={label} value={r.task[f]} onChange={(e) => edit(r.id, { [f]: e.target.value.replace(/\s/g, '') })} />
                  </label>
                ))}
                <label className="field" style={{ flex: 1, minWidth: 180 }}>
                  <span>Command</span>
                  <input className="in mono" aria-label="Command" value={r.task.command} onChange={(e) => edit(r.id, { command: e.target.value.replace(/\n/g, ' ') })} />
                </label>
                <button type="button" className="btn" onClick={() => remove(r.id)}>
                  Remove
                </button>
              </div>
            )
          })}
        </div>
      )}
      <NetChange change={change} short={short} helpTopic={HELP.systemCron} show={body !== null} />
    </>
  )
}

type Props = { routerId: string; routerName: string }

/** The crontab as rows or as text (D7): the router checks every field and names the line it refuses. */
export function CronTab({ routerId, routerName }: Props) {
  const short = routerName.split(' · ')[0] || routerId
  const state = useQuery({ queryKey: ['system-crontab', routerId], queryFn: () => apiFetch<CronState>(`/api/routers/${routerId}/system/crontab`) })
  return (
    <section className="card stack" aria-labelledby="system-cron-h">
      <div className="hrow">
        <h2 id="system-cron-h">Scheduled tasks</h2>
        <Help topic={HELP.systemCron} />
      </div>
      {state.error && <div className="note x">{state.error instanceof ApiError ? state.error.detail : state.error.message}</div>}
      {state.data && <div className="muted">{cronLine(state.data)}</div>}
      {state.data?.note && <div className="note w">{state.data.note}</div>}
      {state.data && <CronForm routerId={routerId} short={short} state={state.data} />}
    </section>
  )
}
