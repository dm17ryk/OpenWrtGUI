import type { GuardOut } from '../api/types'

export function guardPillText(guard: GuardOut | undefined): string {
  if (!guard) return 'Checking Bench Guard…'
  if (!guard.live) return 'No harness running · writes allowed'
  const first = guard.reasons[0]
  const what = first ? (first.kind === 'process' ? first.detail : first.text) : 'A harness'
  return `${what} running · read-only`
}

export function guardReasonText(guard: GuardOut): string {
  return guard.reasons.map((r) => r.text).join('; ')
}
