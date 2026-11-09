import { useQuery } from '@tanstack/react-query'
import { useState, type KeyboardEvent } from 'react'
import { ApiError, apiFetch, postJson } from '../../api/client'
import type { AtResult, GuardOut } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { guardReasonText } from '../../shell/guardText'

const HISTORY = 50
// the same forms as src/openwrtgui/lte/at.py is_query (v0.6a plan D5): they cannot change the modem
const QUERY = /^AT(I|\+CSQ|\+CGM[IMR]|[+%][A-Z0-9]+(\?|=\?))?$/i

function isQuery(text: string): boolean {
  return QUERY.test(text.trim())
}

type Entry = { id: number; command: string; result?: AtResult; error?: string }

function Answer({ entry }: { entry: Entry }) {
  const status = entry.result?.status
  return (
    <div className="stack" style={{ gap: 2 }}>
      <span className="mono">&gt; {entry.command}</span>
      {entry.result?.lines.map((line, i) => (
        <span key={i} className="mono">
          {line}
        </span>
      ))}
      {status && <span className={status === 'OK' ? 'b air' : status === 'ERROR' ? 'b bad' : 'b park'}>{status}</span>}
      {(entry.result?.error ?? entry.error) && status !== 'OK' && <span className="muted">{entry.result?.error ?? entry.error}</span>}
    </div>
  )
}

/** A console like the terminal (D5): no preview, every line audited, the last 50 commands recalled with Up / Down. */
export function AtConsole({ routerId }: { routerId: string }) {
  const guard = useQuery({ queryKey: ['guard'], queryFn: () => apiFetch<GuardOut>('/api/guard') })
  const live = guard.data?.live ?? false
  const [text, setText] = useState('')
  const [entries, setEntries] = useState<Entry[]>([])
  const [history, setHistory] = useState<string[]>([])
  const [recall, setRecall] = useState<number | null>(null)
  const [asking, setAsking] = useState(false)
  const [isBusy, setBusy] = useState(false)
  const command = text.trim()
  const query = isQuery(command)
  const blocked = live && !query

  const send = async (confirmed: boolean): Promise<void> => {
    setAsking(false)
    setBusy(true)
    setHistory((h) => [...h.filter((c) => c !== command), command].slice(-HISTORY))
    setRecall(null)
    setText('')
    const id = Date.now() + Math.random()
    try {
      const result = await postJson<AtResult>(`/api/routers/${routerId}/lte/at`, { command, confirmed })
      setEntries((e) => [...e, { id, command, result }].slice(-HISTORY))
    } catch (err) {
      setEntries((e) => [...e, { id, command, error: err instanceof ApiError ? err.detail : String(err) }].slice(-HISTORY))
    } finally {
      setBusy(false)
    }
  }
  const onSend = (): void => {
    if (!command) return
    if (query) void send(false)
    else setAsking(true)
  }
  const onKey = (e: KeyboardEvent<HTMLInputElement>): void => {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (!blocked && !isBusy) onSend()
    } else if (e.key === 'ArrowUp' && history.length > 0) {
      e.preventDefault()
      const next = recall === null ? history.length - 1 : Math.max(0, recall - 1)
      setRecall(next)
      setText(history[next])
    } else if (e.key === 'ArrowDown' && recall !== null) {
      e.preventDefault()
      const next = recall + 1
      setRecall(next < history.length ? next : null)
      setText(next < history.length ? history[next] : '')
    }
  }

  return (
    <section className="card stack" aria-labelledby="lte-at-h">
      <div className="hrow">
        <h2 id="lte-at-h">AT console</h2>
        <Help topic={HELP.lteAt} />
      </div>
      {entries.length > 0 && (
        <div className="code stack" role="log" aria-label="AT console output" style={{ gap: 8 }}>
          {entries.map((entry) => (
            <Answer key={entry.id} entry={entry} />
          ))}
        </div>
      )}
      <div className="row">
        <input
          className="in mono"
          style={{ flex: 1 }}
          aria-label="AT command"
          placeholder="AT+CSQ"
          maxLength={200}
          autoComplete="off"
          spellCheck={false}
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            setAsking(false)
          }}
          onKeyDown={onKey}
        />
        <button className="btn pri" type="button" disabled={!command || blocked || isBusy} onClick={onSend}>
          Send
        </button>
      </div>
      {blocked && guard.data && <div className="note w">This command may change the modem, so it waits for the run: {guardReasonText(guard.data)}. Queries still work.</div>}
      {asking && (
        <div className="note w row" role="group" aria-label="Confirm AT command">
          <span>This command may change the modem. Send it?</span>
          <div className="spacer" />
          <button className="btn pri" type="button" onClick={() => void send(true)}>
            Send
          </button>
          <button className="btn" type="button" onClick={() => setAsking(false)}>
            Cancel
          </button>
        </div>
      )}
    </section>
  )
}
