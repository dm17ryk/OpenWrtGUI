import { useEffect, useState } from 'react'
import { ApiError, postJson, putJson } from '../../api/client'
import type { ToolCard, ToolCommand, ToolParam } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { toolsPath } from './useRunOutput'

const MAX_COMMANDS = 12
const MAX_PARAMS = 4

type ParamDraft = { name: string; kind: ToolParam['kind']; choices: string; pattern: string; minimum: string; maximum: string }
type CommandDraft = { label: string; args: string; write: boolean; params: ParamDraft[] }
type Draft = { name: string; commands: CommandDraft[] }

const words = (text: string): string[] => text.split(/\s+/).filter(Boolean)
const optional = (text: string): number | null => (text.trim() === '' ? null : Number(text))

function toDraft(card: ToolCard): Draft {
  return {
    name: card.name,
    commands: card.commands.map((c) => ({
      label: c.label,
      args: c.args.join(' '),
      write: c.write,
      params: c.params.map((p) => ({
        name: p.name,
        kind: p.kind,
        choices: p.choices.join(' '),
        pattern: p.pattern ?? '',
        minimum: p.minimum?.toString() ?? '',
        maximum: p.maximum?.toString() ?? '',
      })),
    })),
  }
}

function toCard(board: string, path: string, draft: Draft): ToolCard {
  const commands: ToolCommand[] = draft.commands.map((c) => ({
    label: c.label.trim(),
    args: words(c.args),
    write: c.write,
    params: c.params.map((p) => ({
      name: p.name.trim(),
      kind: p.kind,
      choices: p.kind === 'choice' ? words(p.choices) : [],
      pattern: p.kind === 'text' && p.pattern.trim() ? p.pattern.trim() : null,
      minimum: p.kind === 'number' ? optional(p.minimum) : null,
      maximum: p.kind === 'number' ? optional(p.maximum) : null,
    })),
  }))
  return { board, path, name: draft.name.trim(), commands }
}

function ParamFields({ param, onChange, onRemove }: { param: ParamDraft; onChange: (p: ParamDraft) => void; onRemove: () => void }) {
  return (
    <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
      <input aria-label="Parameter name" value={param.name} size={8} onChange={(e) => onChange({ ...param, name: e.target.value })} />
      <select aria-label={`Kind of ${param.name}`} value={param.kind} onChange={(e) => onChange({ ...param, kind: e.target.value as ParamDraft['kind'] })}>
        <option value="choice">choice</option>
        <option value="text">text</option>
        <option value="number">number</option>
      </select>
      {param.kind === 'choice' && (
        <input aria-label={`Choices for ${param.name}`} value={param.choices} onChange={(e) => onChange({ ...param, choices: e.target.value })} />
      )}
      {param.kind === 'text' && (
        <input aria-label={`Pattern for ${param.name}`} placeholder="letters, digits . _ : -" value={param.pattern} onChange={(e) => onChange({ ...param, pattern: e.target.value })} />
      )}
      {param.kind === 'number' && (
        <>
          <input aria-label={`Minimum of ${param.name}`} type="number" size={6} value={param.minimum} onChange={(e) => onChange({ ...param, minimum: e.target.value })} />
          <input aria-label={`Maximum of ${param.name}`} type="number" size={6} value={param.maximum} onChange={(e) => onChange({ ...param, maximum: e.target.value })} />
        </>
      )}
      <button className="btn" type="button" onClick={onRemove}>
        Remove {param.name}
      </button>
    </div>
  )
}

type Props = {
  board: string
  path: string
  usage: string | null
  initial?: ToolCard
  onClose: () => void
  onSaved: (card: ToolCard) => void
}

/** Promote to a card (decision D9): commands filled from the usage line, edited here, saved per board. */
export function PromoteDialog({ board, path, usage, initial, onClose, onSaved }: Props) {
  const [draft, setDraft] = useState<Draft | null>(initial ? toDraft(initial) : null)
  const [error, setError] = useState<string | null>(null)
  const [isSaving, setSaving] = useState(false)
  const program = path.split('/').pop() ?? path
  useEffect(() => {
    if (initial) return undefined
    let live = true
    postJson<ToolCard>(`${toolsPath(board)}/prefill`, { path, usage })
      .then((card) => live && setDraft(toDraft(card)))
      .catch((err: unknown) => live && setError(err instanceof ApiError ? err.detail : String(err)))
    return () => {
      live = false
    }
  }, [board, path, usage, initial])
  const setCommand = (i: number, next: CommandDraft): void => {
    if (draft) setDraft({ ...draft, commands: draft.commands.map((c, j) => (j === i ? next : c)) })
  }
  const save = async (): Promise<void> => {
    if (!draft) return
    setSaving(true)
    setError(null)
    try {
      onSaved(await putJson<ToolCard>(toolsPath(board), toCard(board, path, draft)))
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err))
    } finally {
      setSaving(false)
    }
  }
  return (
    <section className="card stack" aria-label={`Promote ${program} to a card`}>
      <div className="hrow">
        <h3>Promote {program} to a card</h3>
        <Help topic={HELP.promote} />
      </div>
      {!draft && !error && <div className="muted">Reading the usage line…</div>}
      {draft && (
        <>
          <label className="row" style={{ gap: 6 }}>
            Card name
            <input value={draft.name} maxLength={40} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          </label>
          {draft.commands.map((c, i) => (
            <fieldset key={i} className="stack" style={{ gap: 6 }}>
              <legend className="mono">
                {program} {c.args || '(no arguments)'}
              </legend>
              <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
                <input aria-label="Command label" value={c.label} maxLength={40} onChange={(e) => setCommand(i, { ...c, label: e.target.value })} />
                <input aria-label="Arguments" value={c.args} onChange={(e) => setCommand(i, { ...c, args: e.target.value })} />
                <label className="row" style={{ gap: 4 }}>
                  <input type="checkbox" checked={c.write} onChange={(e) => setCommand(i, { ...c, write: e.target.checked })} />
                  Changes the router
                </label>
                <button className="btn" type="button" onClick={() => setDraft({ ...draft, commands: draft.commands.filter((_, j) => j !== i) })}>
                  Remove command
                </button>
              </div>
              {c.params.map((p, k) => (
                <ParamFields
                  key={k}
                  param={p}
                  onChange={(next) => setCommand(i, { ...c, params: c.params.map((q, m) => (m === k ? next : q)) })}
                  onRemove={() => setCommand(i, { ...c, params: c.params.filter((_, m) => m !== k) })}
                />
              ))}
              {c.params.length < MAX_PARAMS && (
                <button
                  className="btn"
                  type="button"
                  onClick={() =>
                    setCommand(i, {
                      ...c,
                      params: [...c.params, { name: `arg${c.params.length + 1}`, kind: 'text', choices: '', pattern: '', minimum: '', maximum: '' }],
                    })
                  }
                >
                  Add parameter
                </button>
              )}
            </fieldset>
          ))}
          <div className="muted">Arguments are words; a parameter goes in as {'{name}'}. Untick “Changes the router” only for a command that just reads.</div>
        </>
      )}
      {error && (
        <div className="note x" role="alert">
          {error}
        </div>
      )}
      <div className="row" style={{ gap: 8 }}>
        {draft && draft.commands.length < MAX_COMMANDS && (
          <button className="btn" type="button" onClick={() => setDraft({ ...draft, commands: [...draft.commands, { label: 'run', args: '', write: true, params: [] }] })}>
            Add command
          </button>
        )}
        <span className="spacer" />
        <button className="btn" type="button" onClick={onClose}>
          Cancel
        </button>
        <button className="btn pri" type="button" disabled={!draft || isSaving} onClick={() => void save()}>
          {isSaving ? 'Saving…' : 'Save card'}
        </button>
      </div>
    </section>
  )
}
