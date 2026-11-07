import type { FirewallState, ModelIn, PinView, Policy, RuleView } from '../../api/types'

type ForwardingConf = FirewallState['conf']['forwardings'][number]

/** One cell of the filtering model: a zone's policy in one direction (`ACCEPT` = Allow all). */
export type Cell = Policy
export type Cells = Record<string, Cell>
type PinId = PinView['id']

export const DIRECTIONS = [
  { id: 'input', label: 'To this router', short: 'to this router' },
  { id: 'forward', label: 'Through the router', short: 'through' },
  { id: 'output', label: 'From this router', short: 'from this router' },
] as const

const PIN_ORDER: readonly PinId[] = ['ssh', 'dhcpdns']

export function cellsOf(state: FirewallState): Cells {
  const out: Cells = {}
  for (const z of state.conf.zones) for (const d of DIRECTIONS) out[`${z.name}.${d.id}`] = z[d.id]
  return out
}

const classOf = (policy: Cell): 'accept' | 'block' => (policy === 'ACCEPT' ? 'accept' : 'block')

/**
 * What a rule does once the cells apply (src/openwrtgui/fw/state.py rule_effect): a rule whose class equals the
 * zone's default does nothing. A forward rule that meets a forwarding keeps the router's answer, as do disabled
 * rules and rules without a zone.
 */
export function effectIn(rule: RuleView, cells: Cells, forwardings: readonly ForwardingConf[] = []): RuleView['effect'] {
  if (!rule.conf.enabled || rule.target_class === 'other' || rule.direction == null || rule.zone == null) return rule.effect
  // a forwarding src→dest makes the default ACCEPT whatever the zone's forward cell says
  if (rule.direction === 'forward' && forwardings.some((f) => f.enabled && f.src === rule.conf.src && f.dest === rule.conf.dest)) return rule.effect
  const cell = cells[`${rule.zone}.${rule.direction}`]
  if (cell === undefined) return rule.effect
  if (classOf(cell) === rule.target_class) return rule.target_class === 'accept' ? 'no-effect-allow' : 'no-effect-block'
  return rule.target_class === 'accept' ? 'allows' : 'blocks'
}

/** Whether the own zone blocks input in these cells, so the app keeps its pins. */
export function needsPins(state: FirewallState, cells: Cells): boolean {
  return state.own_zone != null && (cells[`${state.own_zone}.input`] ?? 'ACCEPT') !== 'ACCEPT'
}

/** The request for the changed cells (and the pins removed while they apply); null when nothing changed. */
export function modelRequest(state: FirewallState, cells: Cells, pinsRemoved: ReadonlySet<string>): ModelIn | null {
  const was = cellsOf(state)
  const changed: Cells = {}
  for (const [key, policy] of Object.entries(cells)) if (was[key] !== policy) changed[key] = policy
  const pins = needsPins(state, cells) ? PIN_ORDER.filter((p) => pinsRemoved.has(p) && state.pins.some((v) => v.id === p)) : []
  if (Object.keys(changed).length === 0 && pins.length === 0) return null
  return { cells: changed, pins_removed: pins }
}
