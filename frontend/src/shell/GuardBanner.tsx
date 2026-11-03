import type { GuardOut } from '../api/types'
import { guardReasonText } from './guardText'

export function GuardBanner({ guard }: { guard: GuardOut | undefined }) {
  if (!guard?.live) return null
  return (
    <div className="guard" role="status">
      <strong>Bench Guard: every router is read-only.</strong>{' '}
      <span>
        {guardReasonText(guard)}. Status, stations and read-only commands still work. Writes come back when it ends.
      </span>
    </div>
  )
}
