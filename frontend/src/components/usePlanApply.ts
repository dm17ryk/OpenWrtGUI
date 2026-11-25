import { useState } from 'react'
import { ApiError, postJson } from '../api/client'
import type { NetApplyResult, NetPlan } from '../api/types'
import { usePreview } from '../screens/wifi/usePreview'

export type PlanApply<R = NetApplyResult> = {
  plan: NetPlan | null
  error: string | null
  isBusy: boolean
  result: R | null
  apply: () => Promise<void>
  clear: () => void
}

/**
 * One change on the Network and Ports screens: its preview from `<base>/preview` while `body` is set, and
 * Apply, which sends the same body with the preview's digest to `<base>/apply` (so only the lines shown run).
 * `onApplied` runs only when the router took the change; the result shows either way.
 */
export function usePlanApply<R = NetApplyResult>(
  base: string,
  body: object | null,
  onApplied: (result: R) => void,
  /** Whether the router took the change; by default the result's `applied` field (SMS has `ok`, USSD `status`). */
  isDone: (result: R) => boolean = (r) => (r as { applied?: boolean }).applied === true,
): PlanApply<R> {
  const preview = usePreview<NetPlan>(`${base}/preview`, body)
  const [isBusy, setBusy] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)
  const [result, setResult] = useState<R | null>(null)
  const plan = preview?.plan ?? null
  const apply = async (): Promise<void> => {
    if (!body || !plan) return
    setBusy(true)
    setApplyError(null)
    setResult(null) // the result on screen is always the last apply's
    try {
      const done = await postJson<R>(`${base}/apply`, { ...body, digest: plan.digest })
      setResult(done)
      // a refused or rolled-back change left the router as it was: keep the user's edits
      if (isDone(done)) onApplied(done)
    } catch (err) {
      setApplyError(err instanceof ApiError ? err.detail : String(err))
    } finally {
      setBusy(false)
    }
  }
  return {
    plan,
    error: applyError ?? preview?.error ?? null,
    isBusy,
    result,
    apply,
    clear: () => {
      setResult(null)
      setApplyError(null)
    },
  }
}
