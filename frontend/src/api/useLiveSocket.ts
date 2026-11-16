import { useCallback, useEffect, useRef, useState } from 'react'
import { openSocket } from './client'

/** Waits before each reconnect; after the last step, every 15 s while the screen stays open (v1.0c D7). */
export const RECONNECT_MS = [1000, 2000, 4000, 8000, 15000] as const
/** Close codes from 4000 up are the app's own refusals (4404: unknown router): they end the socket. */
const APP_CLOSE = 4000
const CONNECTING = 0

export type LiveSocketState = {
  phase: 'connecting' | 'open' | 'reconnecting' | 'ended'
  attempt: number
  reason: string | null
}

export type LiveSocket = LiveSocketState & {
  /** Sends when the socket is past connecting; otherwise the text is dropped (the screen asks again on open). */
  send: (text: string) => void
}

/** The note a screen shows for its socket: null while it is open or connecting. */
export function reconnectText(state: LiveSocketState): string | null {
  if (state.phase === 'reconnecting') return `Lost the connection to OpenWrtGUI; reconnecting (attempt ${state.attempt})`
  if (state.phase === 'ended') return state.reason ?? 'The connection to OpenWrtGUI ended'
  return null
}

/** A websocket that reconnects by itself after an unexpected close (LTE, RF live, System status). */
const CONNECTING_STATE: LiveSocketState = { phase: 'connecting', attempt: 0, reason: null }

export function useLiveSocket<T>(path: string | null, params: Record<string, string> | undefined, onMessage: (msg: T) => void): LiveSocket {
  const query = new URLSearchParams(params ?? {}).toString()
  const key = path === null ? null : `${path}?${query}`
  // the state of the socket for one path; another path starts out connecting
  const [kept, setKept] = useState<{ key: string | null; state: LiveSocketState }>({ key: null, state: CONNECTING_STATE })
  const handler = useRef(onMessage)
  const socket = useRef<WebSocket | null>(null)

  useEffect(() => {
    handler.current = onMessage
  })

  useEffect(() => {
    if (path === null) return undefined
    const asked: Record<string, string> = {}
    new URLSearchParams(query).forEach((value, name) => {
      asked[name] = value
    })
    const ownKey = `${path}?${query}`
    const setState = (state: LiveSocketState): void => setKept({ key: ownKey, state })
    let attempt = 0
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const open = (): void => {
      const ws = openSocket(path, asked)
      socket.current = ws
      ws.onopen = () => setState({ phase: 'open', attempt, reason: null })
      ws.onmessage = (ev: MessageEvent<string>) => {
        attempt = 0
        setKept((k) => (k.key === ownKey && k.state.phase === 'open' && k.state.attempt === 0 ? k : { key: ownKey, state: { phase: 'open', attempt: 0, reason: null } }))
        handler.current(JSON.parse(ev.data) as T)
      }
      ws.onclose = (ev: CloseEvent) => {
        socket.current = null
        if (stopped) return
        if (ev.code >= APP_CLOSE) {
          setState({ phase: 'ended', attempt, reason: ev.reason || null })
          return
        }
        const delay = RECONNECT_MS[Math.min(attempt, RECONNECT_MS.length - 1)]
        attempt += 1
        setState({ phase: 'reconnecting', attempt, reason: null })
        timer = setTimeout(open, delay)
      }
    }
    open()
    return () => {
      stopped = true
      if (timer !== undefined) clearTimeout(timer)
      const ws = socket.current
      if (ws) {
        ws.onclose = null
        ws.close()
      }
      socket.current = null
    }
  }, [path, query])

  const send = useCallback((text: string): void => {
    const ws = socket.current
    if (ws && ws.readyState !== CONNECTING) ws.send(text)
  }, [])

  const state = kept.key === key ? kept.state : CONNECTING_STATE
  return { ...state, send }
}
