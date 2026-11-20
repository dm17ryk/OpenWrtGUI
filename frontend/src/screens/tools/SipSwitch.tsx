import { useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'
import type { SipAlgZones } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

type Target = { zone: string; on: boolean }

/**
 * Switching SIP ALG per zone (v1.2b R7): one row per zone that runs conntrack helpers, each with its button. The
 * change goes through the firewall's 60 s rollback and is proven in fw4's ruleset; then the badge reads again.
 */
export function SipSwitch({ routerId, zones, routerName }: { routerId: string; zones: SipAlgZones; routerName: string }) {
  const id = useId()
  const client = useQueryClient()
  const [target, setTarget] = useState<Target | null>(null)
  const change = usePlanApply(`/api/routers/${routerId}/firewall/sip-alg`, target, () => {
    setTarget(null)
    void client.invalidateQueries({ queryKey: ['sip-alg', routerId] })
    void client.invalidateQueries({ queryKey: ['sip-zones', routerId] })
  })
  if (zones.state === 'unknown' || zones.zones.length === 0) return null
  return (
    <section className="stack" aria-labelledby={`${id}-h`}>
      <div className="hrow">
        <h3 id={`${id}-h`}>Switch SIP ALG</h3>
        <Help topic={HELP.toolsSipSwitch} />
      </div>
      {zones.zones.map((z) => (
        <div key={z.zone} className="row" style={{ gap: 12 }}>
          <span>{`Zone ${z.zone} · SIP ALG ${z.sip ? 'on' : 'off'}`}</span>
          <button
            className="btn"
            type="button"
            disabled={change.isBusy}
            onClick={() => {
              change.clear()
              setTarget({ zone: z.zone, on: !z.sip })
            }}
          >
            {`Turn SIP ALG ${z.sip ? 'off' : 'on'} in zone ${z.zone}`}
          </button>
        </div>
      ))}
      <NetChange change={change} short={routerName} helpTopic={HELP.toolsSipSwitch} show={target !== null} provenText="Switched and proven" />
    </section>
  )
}
