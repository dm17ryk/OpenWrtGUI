import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { postJson } from '../../api/client'
import type { LteRecoverJob, RungResult } from '../../api/types'
import { isRecovering } from './useLteRecover'

const PHASE: Record<LteRecoverJob['phase'], string> = {
  running: 'Running',
  works: 'LTE works',
  recovered: 'Recovered',
  'not recovered': 'Not recovered',
  stopped: 'Stopped',
  failed: 'Failed',
}

function rungText(rung: RungResult, index: number, job: LteRecoverJob): string {
  if (rung.outcome) return rung.detail ? `${rung.outcome} (${rung.detail})` : rung.outcome
  return job.phase === 'running' && job.current === index ? 'running' : 'waiting'
}

type Props = { routerId: string; job: LteRecoverJob }

/** Recover's progress (spec 4.3): what was wrong, each step with its outcome, Stop while it runs, and what to do
 *  when nothing helped. */
export function RecoverPanel({ routerId, job }: Props) {
  const client = useQueryClient()
  const [stopping, setStopping] = useState(false)
  const running = isRecovering(job)

  async function stop() {
    setStopping(true)
    try {
      const now = await postJson<LteRecoverJob | null>(`/api/routers/${routerId}/lte/recover/stop`)
      if (now) client.setQueryData(['lte-recover', routerId], now)
    } finally {
      setStopping(false)
    }
  }

  return (
    <section className="card stack" aria-labelledby="lte-recover-h">
      <div className="hrow">
        <h2 id="lte-recover-h">Recover</h2>
        <span className={running ? 'b park' : job.phase === 'recovered' || job.phase === 'works' ? 'b air' : 'b'}>{PHASE[job.phase]}</span>
      </div>
      {job.diagnosis.length > 0 && <p>Found: {job.diagnosis.join('; ')}</p>}
      <ol aria-label="Steps" className="stack">
        {job.rungs.map((rung, i) => (
          <li key={rung.name}>
            {rung.name}: {rungText(rung, i, job)}
          </li>
        ))}
      </ol>
      {running && (
        <button type="button" onClick={() => void stop()} disabled={stopping}>
          Stop
        </button>
      )}
      {job.detail && <p role="status">{job.detail}</p>}
      {job.error && <p role="alert" className="note x">{job.error}</p>}
      {job.phase === 'not recovered' && (
        <p>
          <Link to={`/routers/${routerId}/system`}>Reboot router</Link> (it asks first).
        </p>
      )}
    </section>
  )
}
