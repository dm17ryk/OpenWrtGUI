import { useState } from 'react'
import type { HelpResult, ToolCard, ToolParam } from '../../api/types'
import { PreviewApply } from '../../components/PreviewApply'
import { HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import { useRunOutput } from './useRunOutput'

/** What a command printed, and its exit status when it failed. */
export function RunResult({ output }: { output: HelpResult }) {
  return (
    <div className="stack" style={{ gap: 4 }}>
      <pre className="code" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
        {output.output.trimEnd() || '(no output)'}
      </pre>
      {output.exit_status !== 0 && <div className="muted">exit {output.exit_status ?? 'unknown'}</div>}
    </div>
  )
}

function ParamInput({ param, value, onChange }: { param: ToolParam; value: string; onChange: (v: string) => void }) {
  if (param.kind === 'choice') {
    return (
      <select aria-label={param.name} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{param.name}…</option>
        {param.choices.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
    )
  }
  return (
    <input
      aria-label={param.name}
      type={param.kind === 'number' ? 'number' : 'text'}
      min={param.minimum ?? undefined}
      max={param.maximum ?? undefined}
      placeholder={param.kind === 'text' ? (param.pattern ?? param.name) : param.name}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

type Props = {
  routerId: string
  card: ToolCard
  live: boolean
  busyTitle?: string
  onEdit: (card: ToolCard) => void
  onRemove: (card: ToolCard) => void
}

/** A promoted card (decision D9): one button per command, its parameters, the exact command, Run. */
export function ToolCardView({ routerId, card, live, busyTitle, onEdit, onRemove }: Props) {
  const [label, setLabel] = useState<string | null>(null)
  const [values, setValues] = useState<Record<string, string>>({})
  const [isRemoving, setRemoving] = useState(false)
  const command = card.commands.find((c) => c.label === label) ?? null
  const isComplete = command !== null && command.params.every((p) => (values[p.name] ?? '') !== '')
  const body = command && isComplete ? { path: card.path, label: command.label, values } : null
  const run = useRunOutput(`/api/routers/${routerId}/discovery/tool`, body)
  const pick = (next: string): void => {
    setLabel(next)
    setValues({})
  }
  return (
    <section className="card stack" aria-label={`Card ${card.name}`}>
      <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
        <strong>{card.name}</strong>
        <span className="mono muted">{card.path}</span>
        <span className="spacer" />
        <HelpTip topic={HELP.promote}>
          <button className="btn" type="button" onClick={() => onEdit(card)}>
            Edit
          </button>
        </HelpTip>
        {isRemoving ? (
          <button className="btn" type="button" onClick={() => onRemove(card)}>
            Remove this card
          </button>
        ) : (
          <button className="btn" type="button" onClick={() => setRemoving(true)}>
            Remove
          </button>
        )}
      </div>
      <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
        {card.commands.map((c) => {
          const isWaiting = c.write && live
          return (
            <button
              key={c.label}
              className="btn"
              type="button"
              aria-pressed={c.label === label}
              disabled={isWaiting}
              title={isWaiting ? busyTitle : c.write ? 'Changes the router' : 'Read-only'}
              onClick={() => pick(c.label)}
            >
              {c.label}
            </button>
          )
        })}
      </div>
      {command && command.params.length > 0 && (
        <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
          {command.params.map((p) => (
            <ParamInput key={p.name} param={p} value={values[p.name] ?? ''} onChange={(v) => setValues({ ...values, [p.name]: v })} />
          ))}
        </div>
      )}
      {body && (
        <PreviewApply
          heading={command?.write ? 'Command that will run (it changes the router)' : 'Command that will run (read-only)'}
          lines={run.plan?.lines ?? []}
          warnings={run.plan?.warnings ?? []}
          error={run.error}
          isBusy={run.isBusy}
          isDisabled={(command?.write ?? true) && live}
          applyLabel="Run"
          onApply={() => void run.run()}
          helpTopic={HELP.promote}
        />
      )}
      {run.output && <RunResult output={run.output} />}
    </section>
  )
}
