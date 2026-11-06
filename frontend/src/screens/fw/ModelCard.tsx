import { useState } from 'react'
import type { FirewallState, PinView, RuleView } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'
import { type Cell, type Cells, cellsOf, DIRECTIONS, effectIn, modelRequest, needsPins } from './model'
import { ruleAction, ruleMatch, ruleWhere } from './rules'

type Block = Exclude<Cell, 'ACCEPT'>
type Props = { routerId: string; routerName: string; short: string; state: FirewallState; onApplied: () => void }

const EFFECT: Record<RuleView['effect'], string> = {
  allows: 'allows',
  blocks: 'blocks',
  'no-effect-allow': 'no effect · zone already allows this',
  'no-effect-block': 'no effect · zone already blocks this',
  other: 'other',
}

function blockOf(cells: Cells): Block {
  const blocked = Object.values(cells).filter((c) => c !== 'ACCEPT')
  return blocked.length > 0 && blocked.every((c) => c === 'DROP') ? 'DROP' : 'REJECT'
}

function pinWarning(pin: PinView, routerName: string, zone: string): string {
  return pin.id === 'ssh'
    ? `Without this rule the app loses ${routerName} as soon as the change applies. The 60 s rollback then restores the old firewall by itself.`
    : `Without this rule devices on ${zone} stop getting addresses and names from ${routerName}, including the panels under test.`
}

function flagSummary(n: number): string {
  const rules = n === 1 ? '1 rule no longer does anything' : `${n} rules no longer do anything`
  return `${rules} in this model. They stay in the config, so switching back restores them; delete them here if you no longer need them.`
}

/**
 * The filtering model (spec 7.6, D11): per zone and direction Allow all or Block all, how blocked traffic is
 * refused, the pins that keep this app's own path open, and what each rule does once the model changes.
 */
export function ModelCard({ routerId, routerName, short, state, onApplied }: Props) {
  const [edited, setEdited] = useState<Cells | null>(null)
  const [removed, setRemoved] = useState<ReadonlySet<string>>(new Set())
  const [asking, setAsking] = useState<string | null>(null)
  const cells = edited ?? cellsOf(state)
  const block = blockOf(cells)
  const body = modelRequest(state, cells, removed)
  const change = usePlanApply(`/api/routers/${routerId}/firewall/model`, body, () => {
    setEdited(null)
    setRemoved(new Set())
    onApplied()
  })
  const setCell = (key: string, policy: Cell): void => {
    setEdited({ ...cells, [key]: policy })
    setAsking(null)
  }
  const setBlock = (to: Block): void =>
    setEdited(Object.fromEntries(Object.entries(cells).map(([k, c]) => [k, c === 'ACCEPT' ? c : to])))
  const setPin = (id: string, gone: boolean): void => {
    const next = new Set(removed)
    if (gone) next.add(id)
    else next.delete(id)
    setRemoved(next)
    setAsking(null)
  }
  const own = state.own_zone ?? ''
  const rows = state.rules.map((r) => ({ rule: r, effect: effectIn(r, cells, state.conf.forwardings) }))
  const flags = rows.filter((r) => r.effect.startsWith('no-effect')).length
  return (
    <>
      <section className="card stack" aria-labelledby="fw-model-h">
        <div className="hrow">
          <h2 id="fw-model-h">Filtering model</h2>
          <Help topic={HELP.fwModel} />
          <span className="muted">
            per zone and direction · <strong>Allow all</strong>: everything passes, your rules block · <strong>Block all</strong>: nothing passes, your rules allow
          </span>
        </div>
        <div className="scroll-x">
          <table className="tbl" aria-label="Filtering model">
            <thead>
              <tr>
                <th>Zone</th>
                {DIRECTIONS.map((d) => (
                  <th key={d.id}>{d.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {state.conf.zones.map((z) => (
                <tr key={z.section}>
                  <td className="nowrap">
                    <strong>{z.name}</strong> <span className="mono muted">{z.networks.join(', ')}</span>
                    {z.name === own && (
                      <div>
                        <span className="b own">carries this app&apos;s SSH</span>
                      </div>
                    )}
                  </td>
                  {DIRECTIONS.map((d) => {
                    const key = `${z.name}.${d.id}`
                    const policy = cells[key] ?? z[d.id]
                    const allow = policy === 'ACCEPT'
                    return (
                      <td key={d.id}>
                        <div className="seg" role="group" aria-label={`${z.name} ${d.label}`}>
                          <button type="button" className={allow ? 'on' : ''} aria-pressed={allow} onClick={() => setCell(key, 'ACCEPT')}>
                            Allow all
                          </button>
                          <button type="button" className={allow ? '' : 'onblock'} aria-pressed={!allow} onClick={() => setCell(key, allow ? block : policy)}>
                            Block all
                          </button>
                        </div>
                        <div className="muted small">{allow ? 'rules block' : policy === 'DROP' ? 'rules allow · rest dropped' : 'rules allow · rest rejected'}</div>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="row">
          <span>Blocked traffic is</span>
          <div className="seg" role="group" aria-label="How blocked traffic is handled">
            <button type="button" className={block === 'REJECT' ? 'on' : ''} aria-pressed={block === 'REJECT'} onClick={() => setBlock('REJECT')}>
              Rejected · sender is told
            </button>
            <button type="button" className={block === 'DROP' ? 'on' : ''} aria-pressed={block === 'DROP'} onClick={() => setBlock('DROP')}>
              Dropped · silent
            </button>
          </div>
        </div>
        {needsPins(state, cells) && state.pins.length > 0 && (
          <div className="stack" style={{ gap: 8 }}>
            <div className="hrow">
              <div className="eyebrow">Kept open by the app on {own}, so it cannot lock itself out</div>
              <Help topic={HELP.fwPins} />
            </div>
            {state.pins.map((p) => {
              const gone = removed.has(p.id)
              return (
                <div key={p.id} className="stack" style={{ gap: 8 }}>
                  <div className="pin">
                    <strong>{p.name}</strong>
                    <span className="mono muted small">{p.match}</span>
                    <span className="muted small">{p.why}</span>
                    <span className="spacer" />
                    {gone ? (
                      <>
                        <span className="b bad">removed</span>
                        <button className="btn" type="button" onClick={() => setPin(p.id, false)}>
                          Put back
                        </button>
                      </>
                    ) : (
                      <HelpTip topic={HELP.fwPins}>
                        <button className="btn" type="button" onClick={() => setAsking(p.id)}>
                          Remove…
                        </button>
                      </HelpTip>
                    )}
                  </div>
                  {asking === p.id && !gone && (
                    <div className="note w row">
                      <span style={{ flex: '1 1 380px' }}>{pinWarning(p, routerName, own)}</span>
                      <button className="btn danger" type="button" onClick={() => setPin(p.id, true)}>
                        Remove anyway
                      </button>
                      <button className="btn" type="button" onClick={() => setAsking(null)}>
                        Keep it
                      </button>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
        <NetChange change={change} short={short} helpTopic={HELP.fwModel} show={body !== null} />
      </section>
      <section className="card stack" aria-labelledby="fw-effect-h">
        <div className="hrow">
          <h2 id="fw-effect-h">Your rules in this model</h2>
          <Help topic={HELP.fwRules} />
          <span className="muted">switching keeps every rule; rules that stop doing anything are flagged</span>
        </div>
        <div className="scroll-x">
          <table className="tbl" aria-label="Your rules in this model">
            <thead>
              <tr>
                <th>Rule</th>
                <th>Where</th>
                <th>Match</th>
                <th>Action</th>
                <th>Packets</th>
                <th>Effect</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ rule, effect }) => {
                const dead = effect.startsWith('no-effect')
                const action = ruleAction(rule.conf.target)
                return (
                  <tr key={rule.conf.section} className={dead ? 'flag' : undefined}>
                    <td>{rule.conf.name ?? rule.conf.section}</td>
                    <td className="mono nowrap">{ruleWhere(rule)}</td>
                    <td className="mono">{ruleMatch(rule.conf)}</td>
                    <td>
                      <span className={`pol ${action.cls}`}>{action.label}</span>
                    </td>
                    <td className="mono">{rule.packets ?? '—'}</td>
                    <td>
                      <span className={`b ${dead ? 'park' : 'neu'}`}>{EFFECT[effect]}</span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {flags > 0 && <div className="note w">{flagSummary(flags)}</div>}
      </section>
    </>
  )
}
