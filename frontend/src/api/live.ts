import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { openSocket } from './client'
import type { LiveMessage, RouterItem } from './types'

const RECONNECT_MS = 2000

/** Apply one /ws/live message to the query cache (exported for tests). */
export function applyLive(client: QueryClient, msg: LiveMessage): void {
  switch (msg.type) {
    case 'guard':
      client.setQueryData(['guard'], msg.state)
      break
    case 'update':
      client.setQueryData(['update'], msg.status)
      break
    case 'update-progress':
      client.setQueryData(['update-progress'], msg)
      break
    case 'status':
    case 'router-offline':
      client.setQueryData<RouterItem[]>(['routers'], (items) =>
        items?.map((item) => {
          if (item.record.id !== msg.router) return item
          if (msg.type === 'status') {
            return { ...item, status: msg.status, health: { ...item.health, online: true, error: null } }
          }
          return { ...item, status: null, health: { online: false, since: msg.since, error: msg.error } }
        }),
      )
      break
  }
}

export function useLive(): void {
  const client = useQueryClient()
  useEffect(() => {
    let socket: WebSocket | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let closed = false
    const connect = (): void => {
      socket = openSocket('/ws/live')
      socket.onmessage = (event: MessageEvent<string>) => applyLive(client, JSON.parse(event.data) as LiveMessage)
      socket.onclose = () => {
        if (!closed) timer = setTimeout(connect, RECONNECT_MS)
      }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(timer)
      socket?.close()
    }
  }, [client])
}
