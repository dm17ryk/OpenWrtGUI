import { useQuery } from '@tanstack/react-query'
import { FitAddon } from '@xterm/addon-fit'
import { Terminal as Xterm } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import { useEffect, useRef, useState } from 'react'
import { NavLink, useParams } from 'react-router'
import { apiFetch, openSocket } from '../api/client'
import type { RouterItem, TerminalMessage } from '../api/types'
import { Help } from '../help/Help'
import { HELP } from '../help/topics'
import { LineConsole } from './LineConsole'
import { commandLine, reduceLines, type ConsoleLine } from './lineConsoleState'

type Mode = 'connecting' | 'pty' | 'line' | 'closed'

function Session({ routerId }: { routerId: string }) {
  const [mode, setMode] = useState<Mode>('connecting')
  const [reason, setReason] = useState<string | null>(null)
  const [canPty, setCanPty] = useState(false)
  const [lines, setLines] = useState<ConsoleLine[]>([])
  const [attempt, setAttempt] = useState(0)
  const socketRef = useRef<WebSocket | null>(null)
  const boxRef = useRef<HTMLDivElement | null>(null)
  const xtermRef = useRef<Xterm | null>(null)
  const socketMode = useRef<Mode>('connecting')

  useEffect(() => {
    socketMode.current = mode
  }, [mode])

  useEffect(() => {
    const box = boxRef.current
    const term = new Xterm({ fontFamily: 'IBM Plex Mono, monospace', fontSize: 13, cursorBlink: true, convertEol: false })
    const fit = new FitAddon()
    term.loadAddon(fit)
    if (box) {
      term.open(box)
      fit.fit()
    }
    xtermRef.current = term
    const socket = openSocket(`/ws/terminal/${routerId}`, { cols: String(term.cols), rows: String(term.rows) })
    socketRef.current = socket
    const send = (msg: object): void => {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(msg))
    }
    const input = term.onData((data) => send({ type: 'input', data }))
    const resize = term.onResize(({ cols, rows }) => send({ type: 'resize', cols, rows }))
    const observer = new ResizeObserver(() => fit.fit())
    if (box) observer.observe(box)
    socket.onmessage = (event: MessageEvent<string>) => {
      const msg = JSON.parse(event.data) as TerminalMessage
      if (msg.type === 'mode') {
        if (msg.mode === 'line-available-pty') {
          setCanPty(true)
          return
        }
        setMode(msg.mode)
        setReason(msg.reason)
        return
      }
      if (msg.type === 'output' && socketMode.current === 'pty') {
        term.write(msg.data)
        return
      }
      setLines((prev) => reduceLines(prev, msg))
    }
    socket.onclose = () => setMode('closed')
    return () => {
      input.dispose()
      resize.dispose()
      observer.disconnect()
      socket.close()
      term.dispose()
    }
  }, [routerId, attempt])

  const run = (line: string): void => {
    setLines((prev) => commandLine(prev, line))
    socketRef.current?.send(JSON.stringify({ type: 'line', text: line }))
  }

  const reconnect = (): void => {
    setCanPty(false)
    setLines([])
    setMode('connecting')
    setAttempt((n) => n + 1)
  }

  return (
    <div className="stack">
      <div className="row">
        <span className={mode === 'pty' ? 'b air' : mode === 'line' ? 'b park' : 'b neu'}>
          {mode === 'pty' ? 'shell' : mode === 'line' ? 'line mode' : mode}
        </span>
        <div className="spacer" />
        {(canPty || mode === 'closed') && (
          <button className="btn" type="button" onClick={reconnect}>
            Reconnect
          </button>
        )}
      </div>
      <div ref={boxRef} style={{ display: mode === 'pty' ? 'block' : 'none', height: 480, background: '#0b0d10', borderRadius: 8, padding: 8 }} />
      {mode !== 'pty' && <LineConsole lines={lines} reason={reason} onRun={run} />}
    </div>
  )
}

export function Terminal() {
  const { id } = useParams()
  const routers = useQuery({ queryKey: ['routers'], queryFn: () => apiFetch<RouterItem[]>('/api/routers') })
  const usable = (routers.data ?? []).filter((r) => r.record.auth === 'key')
  const current = usable.find((r) => r.record.id === id)
  return (
    <main className="wrap">
      <div>
        <div className="eyebrow">Terminal · commands are written to the audit log</div>
        <div className="hrow">
          <h1>{current ? current.record.name : 'Terminal'}</h1>
          <Help topic={HELP.terminal} />
        </div>
      </div>
      <nav className="row" aria-label="Routers" style={{ gap: 6 }}>
        {usable.map((r) => (
          <NavLink key={r.record.id} to={`/terminal/${r.record.id}`} className={({ isActive }) => (isActive ? 'btn pri' : 'btn')}>
            {r.record.name}
          </NavLink>
        ))}
      </nav>
      {current ? (
        <section className="card">
          <Session key={current.record.id} routerId={current.record.id} />
        </section>
      ) : (
        <div className="muted">Pick a router. Routers without the app key cannot open a terminal.</div>
      )}
    </main>
  )
}
