import { useState } from 'react'
import { ApiError, postJson } from '../api/client'
import type { NetApplyResult, NetPlan } from '../api/types'
import { usePreview } from '../screens/wifi/usePreview'

export type PlanApply = {
  plan: NetPlan | null
  error: string | null
  isBusy: boolean
  result: NetApplyResult | null
  apply: () => Promise<void>
  clear: () => void
}

/**
 * One change on the Network and Ports screens: its preview from `<base>/preview` while `body` is set, and
 * Apply, which sends the same body with the preview's digest to `<base>/apply` (so only the lines shown run).
 * `onApplied` runs only when the router took the change; the result shows either way.
 */
export function usePlanApply(base: string, body: object | null, onApplied: (result: NetApplyResult) => void): PlanApply {
  const preview = usePreview<NetPlan>(`${base}/preview`, body)
  const [isBusy, setBusy] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)
  const [result, setResult] = useState<NetApplyResult | null>(null)
  const plan = preview?.plan ?? null
  const apply = async (): Promise<void> => {
    if (!body || !plan) return
    setBusy(true)
    setApplyError(null)
    try {
      const done = await postJson<NetApplyResult>(`${base}/apply`, { ...body, digest: plan.digest })
      setResult(done)
      // a refused or rolled-back change left the router as it was: keep the user's edits
      if (done.applied) onApplied(done)
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
