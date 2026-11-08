import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { ServiceRow } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

type Action = 'start' | 'stop' | 'restart'
type Change = { name: string; action: Action }
type Props = { routerId: string; services: ServiceRow[]; readAt: string; live: boolean; busyTitle?: string }

const ACTIONS: Array<[Action, string]> = [
  ['start', 'Start'],
  ['stop', 'Stop'],
  ['restart', 'Restart'],
]

function stateText(running: boolean | null | undefined): string {
  return running === true ? 'running' : running === false ? 'stopped' : 'unknown'
}

/** Custom services (spec 7.8): the init scripts of custom packages and of the overlay, with Start/Stop/Restart. */
export function ServicesTable({ routerId, services, readAt, live, busyTitle }: Props) {
  const client = useQueryClient()
  const [change, setChange] = useState<Change | null>(null)
  // what the last proven action left, until the next read of the router replaces it
  const [seen, setSeen] = useState<{ readAt: string; running: Record<string, boolean> }>({ readAt, running: {} })
  const proven = seen.readAt === readAt ? seen.running : {}
  const action = usePlanApply(`/api/routers/${routerId}/discovery/service`, change, (result) => {
    if (change && result.verified) setSeen({ readAt, running: { ...proven, [change.name]: change.action !== 'stop' } })
    setChange(null)
    void client.invalidateQueries({ queryKey: ['discovery', routerId] })
  })
  if (services.length === 0) return null
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="hrow">
        <h3>Custom services</h3>
        <Help topic={HELP.customServices} />
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table aria-label="Custom services">
          <thead>
            <tr>
              <th>Service</th>
              <th>From</th>
              <th>Now</th>
              <th>At boot</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {services.map((s) => (
              <tr key={s.name}>
                <td className="mono">{s.name}</td>
                <td>{s.package ?? 'added after flashing'}</td>
                <td>{stateText(proven[s.name] ?? s.running)}</td>
                <td>{s.enabled === true ? 'enabled' : s.enabled === false ? 'disabled' : 'unknown'}</td>
                <td>
                  <div className="row" style={{ gap: 4 }}>
                    {ACTIONS.map(([a, label]) => (
                      <HelpTip key={a} topic={HELP.customServices}>
                        <button
                          className="btn"
                          type="button"
                          disabled={live}
                          title={live ? busyTitle : undefined}
                          aria-pressed={change?.name === s.name && change.action === a}
                          onClick={() => setChange({ name: s.name, action: a })}
                        >
                          {label}
                        </button>
                      </HelpTip>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <NetChange change={action} short={routerId} helpTopic={HELP.customServices} show={change !== null && !live} provenText="Done and checked" />
    </div>
  )
}
