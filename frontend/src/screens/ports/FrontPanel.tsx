import { useState } from 'react'
import type { PortEnableIn, PortView, PortsState } from '../../api/types'
import { Toggle } from '../../components/Toggle'
import { usePlanApply } from '../../components/usePlanApply'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

function linkText(p: PortView): string {
  if (!p.link) return 'no link'
  const duplex = p.full_duplex === true ? ' full' : p.full_duplex === false ? ' half' : ''
  return `link · ${p.speed_mbps ?? '?'} Mb/s${duplex}`
}

type Props = { routerId: string; short: string; state: PortsState; onApplied: () => void }

/** The sockets as on the case: link, speed, and an on/off switch, except on the one carrying this app's SSH. */
export function FrontPanel({ routerId, short, state, onApplied }: Props) {
  const [pending, setPending] = useState<PortEnableIn | null>(null)
  const change = usePlanApply(`/api/routers/${routerId}/ports/enable`, pending, () => {
    setPending(null)
    onApplied()
  })
  const isOn = (p: PortView): boolean => (pending?.port === p.num && pending.on != null ? pending.on : p.enabled === true)
  const anyOff = state.ports.some((p) => p.enabled === false)
  return (
    <section className="card stack" aria-labelledby="panel-h">
      <div className="row">
        <div className="hrow">
          <h2 id="panel-h">Front panel</h2>
          <Help topic={HELP.portsPanel} />
        </div>
        <div className="spacer" />
        {state.can_disable && (
          <HelpTip topic={HELP.portsPanel}>
            <button className="btn" type="button" disabled={!anyOff} onClick={() => setPending({ all_on: true })}>
              Enable all ports
            </button>
          </HelpTip>
        )}
      </div>
      <div className="sockets">
        {state.ports.map((p) => (
          <div key={p.num} className={p.lock ? 'socket own' : 'socket'} role="group" aria-label={p.label}>
            <strong>{p.label}</strong>
            <span className="muted mono">port {p.num}</span>
            <span className="row" style={{ gap: 6 }}>
              <span className="dot" aria-hidden="true" style={{ background: p.link ? 'var(--ok)' : 'var(--line)' }} />
              {linkText(p)}
            </span>
            {p.lock ? (
              <span className="hrow">
                <span className="b own">{p.lock}</span>
                <Help topic={HELP.portsOwn} />
              </span>
            ) : state.can_disable && p.enabled !== null ? (
              <Toggle label={`Enable ${p.label}`} checked={isOn(p)} onChange={(on) => setPending(on === p.enabled ? null : { port: p.num, on })}>
                {isOn(p) ? 'on' : 'off'}
              </Toggle>
            ) : (
              <span className="muted">cannot be turned off</span>
            )}
          </div>
        ))}
      </div>
      <div className="muted">Disabled until the next reboot or network reload: a socket turned off here comes back on by itself then.</div>
      <NetChange change={change} short={short} helpTopic={HELP.portsPanel} show={pending !== null} />
    </section>
  )
}
