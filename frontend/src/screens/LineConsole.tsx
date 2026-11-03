import { useState, type FormEvent } from 'react'
import type { ConsoleLine } from './lineConsoleState'

const COLOR: Record<ConsoleLine['kind'], string> = {
  out: 'var(--code-ink)',
  cmd: '#7FD1A8',
  refused: '#F08A6C',
  exit: 'var(--code-c)',
  error: '#F08A6C',
}

type Props = { lines: ConsoleLine[]; reason: string | null; onRun: (line: string) => void }

export function LineConsole({ lines, reason, onRun }: Props) {
  const [text, setText] = useState('')
  const submit = (e: FormEvent): void => {
    e.preventDefault()
    const line = text.trim()
    if (!line) return
    onRun(line)
    setText('')
  }
  return (
    <div className="stack">
      {reason && (
        <div className="note w">
          <strong>Read-only mode: a harness run is in progress.</strong> {reason}
        </div>
      )}
      <div className="code" style={{ minHeight: 260, maxHeight: 520, overflowY: 'auto' }} aria-live="polite">
        {lines.map((l) => (
          <div key={l.id} style={{ color: COLOR[l.kind], whiteSpace: 'pre-wrap' }}>
            {l.text}
          </div>
        ))}
      </div>
      <form className="row" onSubmit={submit} style={{ gap: 8 }}>
        <label htmlFor="cmd" className="mono" style={{ color: 'var(--muted)' }}>
          $
        </label>
        <input id="cmd" aria-label="Command" className="in mono" style={{ flex: '1 1 300px' }} value={text} onChange={(e) => setText(e.target.value)} autoComplete="off" spellCheck={false} />
        <button className="btn pri" type="submit">
          Run
        </button>
      </form>
    </div>
  )
}
