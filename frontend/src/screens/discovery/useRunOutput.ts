import { useState } from 'react'
import { ApiError, postJson } from '../../api/client'
import type { HelpResult, NetPlan } from '../../api/types'
import { usePreview } from '../wifi/usePreview'

export type RunOutput = {
  plan: NetPlan | null
  error: string | null
  isBusy: boolean
  output: HelpResult | null
  run: () => Promise<void>
}

/** `/api/tools/{board}`: the promoted cards of one board. */
export function toolsPath(board: string): string {
  return `/api/tools/${encodeURIComponent(board)}`
}

/**
 * A command whose answer is what it printed (Run --help, a card command): its preview from `<base>/preview`
 * while `body` is set, and Run, which sends the same body with the preview's digest to `<base>/apply`.
 */
export function useRunOutput(base: string, body: object | null): RunOutput {
  const preview = usePreview<NetPlan>(`${base}/preview`, body)
  const [isBusy, setBusy] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [output, setOutput] = useState<HelpResult | null>(null)
  const plan = preview?.plan ?? null
  const run = async (): Promise<void> => {
    if (!body || !plan) return
    setBusy(true)
    setRunError(null)
    setOutput(null)
    try {
      setOutput(await postJson<HelpResult>(`${base}/apply`, { ...body, digest: plan.digest }))
    } catch (err) {
      setRunError(err instanceof ApiError ? err.detail : String(err))
    } finally {
      setBusy(false)
    }
  }
  return { plan, error: runError ?? preview?.error ?? null, isBusy, output, run }
}
