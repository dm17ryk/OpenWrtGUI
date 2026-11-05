import { useEffect, useState } from 'react'
import { ApiError, postJson } from '../../api/client'
import type { PlanOut } from '../../api/types'

export type Preview = { plan: PlanOut | null; error: string | null }

/**
 * The router's preview of a request, asked 300 ms after the last change. Only the answer for the
 * current request is returned, so a slow answer to an older one never shows.
 */
export function usePreview(path: string, body: unknown): Preview | null {
  const key = body === null ? null : `${path} ${JSON.stringify(body)}`
  const [answer, setAnswer] = useState<{ key: string; preview: Preview } | null>(null)
  useEffect(() => {
    if (key === null) return undefined
    let live = true
    const timer = setTimeout(() => {
      postJson<PlanOut>(path, body)
        .then((plan) => live && setAnswer({ key, preview: { plan, error: null } }))
        .catch(
          (err: unknown) =>
            live && setAnswer({ key, preview: { plan: null, error: err instanceof ApiError ? err.detail : String(err) } }),
        )
    }, 300)
    return () => {
      live = false
      clearTimeout(timer)
    }
    // body is part of key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return answer && answer.key === key ? answer.preview : null
}
