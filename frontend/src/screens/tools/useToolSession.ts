import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch, postJson } from '../../api/client'
import type { ToolSessionView } from '../../api/types'

const POLL_MS = 1000

export type SessionKind = ToolSessionView['kind']

function newest(sessions: ToolSessionView[] | undefined, kind: SessionKind): ToolSessionView | null {
  const mine = (sessions ?? []).filter((s) => s.kind === kind)
  return mine.reduce<ToolSessionView | null>((a, s) => (a === null || s.started_at >= a.started_at ? s : a), null)
}

function errorText(e: unknown): string {
  return e instanceof ApiError ? e.detail : String(e)
}

/**
 * A router tool that runs for a while (v1.2b R2): the newest session of one kind on the router, read every second
 * while it runs, with Start and Stop. A refused Start (423 during a harness run, 409 while another runs) is the error.
 */
export function useToolSession(routerId: string, kind: SessionKind) {
  const client = useQueryClient()
  const key = ['tool-sessions', routerId]
  const [error, setError] = useState<string | null>(null)
  const sessions = useQuery({
    queryKey: key,
    queryFn: () => apiFetch<ToolSessionView[]>(`/api/routers/${routerId}/tools/sessions`),
    refetchInterval: (q) => (newest(q.state.data, kind)?.running ? POLL_MS : false),
    refetchIntervalInBackground: false,
  })
  const session = newest(sessions.data, kind)

  async function start(path: string, body: object): Promise<void> {
    setError(null)
    try {
      await postJson<ToolSessionView>(path, body)
    } catch (e) {
      setError(errorText(e))
    }
    await client.invalidateQueries({ queryKey: key })
  }

  async function stop(): Promise<void> {
    if (session === null) return
    setError(null)
    try {
      await postJson<ToolSessionView>(`/api/routers/${routerId}/tools/sessions/${session.id}/stop`)
    } catch (e) {
      setError(errorText(e))
    }
    await client.invalidateQueries({ queryKey: key })
  }

  return { session, start, stop, error }
}
