import type { RebootJob } from '../../api/types'

const ARMED: Record<RebootJob['kind'], (short: string) => string> = {
  reboot: (short) => `Armed: ${short} reboots in 2 s`,
  restore: (short) => `Restored: ${short} reboots in 2 s`,
  reset: (short) => `Armed: ${short} erases its settings in 2 s`,
}

function phaseText(job: RebootJob, short: string): string {
  if (job.phase === 'armed') return ARMED[job.kind](short)
  if (job.phase === 'waiting') return job.kind === 'reset' ? `Waiting for ${short} to stop answering…` : `Waiting for ${short} to answer with a fresh uptime…`
  if (job.phase === 'back') return job.detail ?? `${short} is back`
  if (job.phase === 'reset') return job.detail ?? `${short} is resetting to defaults`
  return job.error ?? (job.kind === 'reset' ? `${short} did not reset` : `${short} is not back`)
}

const TONE: Record<RebootJob['phase'], string> = {
  armed: 'note w',
  waiting: 'note w',
  back: 'note',
  reset: 'note',
  'not back': 'note x',
  'not reset': 'note x',
}

type Props = { job: RebootJob; short: string; label: string }

/** Where a reboot, restore or reset is: armed, waiting, then back (or reset), or why not. */
export function JobStatus({ job, short, label }: Props) {
  const ended = job.phase === 'back' || job.phase === 'reset'
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className={TONE[job.phase]} role="status" aria-label={label}>
        {phaseText(job, short)}
      </div>
      {ended && job.error && <div className="note w">{job.error}</div>}
    </div>
  )
}
