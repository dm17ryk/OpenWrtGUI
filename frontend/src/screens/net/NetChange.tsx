import { CheckList } from '../../components/CheckList'
import { PreviewApply } from '../../components/PreviewApply'
import type { PlanApply } from '../../components/usePlanApply'
import { HELP } from '../../help/topics'

/** While a change with rollback applies: the app reconnects and confirms, or the router restores itself. */
export function RollbackWait({ router, target }: { router: string; target: string | null }) {
  return (
    <div className="note" role="status" aria-label="Waiting for the router">
      Applying with a 60 s rollback: waiting for {router} to answer{target ? ` at ${target}` : ''}…
    </div>
  )
}

type Props = { change: PlanApply; short: string; helpTopic: string; show: boolean; applyLabel?: string; provenText?: string }

/**
 * A Network card's preview and Apply. A change that can cut this app off (routes, addresses) comes back with
 * `rollback` and applies with one; the rest apply plainly and are checked against the saved config.
 */
export function NetChange({ change, short, helpTopic, show, applyLabel, provenText }: Props) {
  if (!show && !change.result) return null
  const rollback = change.plan?.rollback ?? false
  const confirmed = change.result?.checks.some((c) => c.name === 'confirmed') ?? false
  return (
    <div className="grid">
      {show && (
        <PreviewApply
          heading={`Commands that will run on ${short}`}
          lines={change.plan?.lines ?? []}
          warnings={change.plan?.warnings ?? []}
          error={change.error}
          isBusy={change.isBusy}
          applyLabel={applyLabel ?? (rollback ? 'Apply with rollback' : 'Apply')}
          onApply={() => void change.apply()}
          helpTopic={rollback ? HELP.netRollback : helpTopic}
        />
      )}
      {show && rollback && change.isBusy && <RollbackWait router={short} target={change.plan?.target_host ?? null} />}
      {change.result && <CheckList result={change.result} provenText={provenText ?? (confirmed ? 'Applied and confirmed' : 'Applied and checked')} />}
    </div>
  )
}
