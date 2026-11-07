import type { FaultIn, NetemIn } from '../../api/types'

export type FaultKind = FaultIn['kind']
export type Flow = NonNullable<FaultIn['flow']>
export type Netem = Required<NetemIn>
export type TargetRef = { mac: string | null; ip: string | null }

/** What the Faults screen has chosen so far: one target and one fault, with its settings. */
export type FaultDraft = {
  target: TargetRef | null
  kind: FaultKind | null
  flow: Flow | null
  loss: number
  netem: Netem
  port: number | null
  ban_s: number
  hold: boolean
  hold_s: number
}

export const FLOWS: readonly Flow[] = ['rtp_in', 'sip_in', 'rtp_out', 'all_in', 'all_out', 'blackout']

export const EMPTY_DRAFT: FaultDraft = {
  target: null,
  kind: null,
  flow: null,
  loss: 100,
  netem: { delay_ms: 0, jitter_ms: 0, distribution: 'uniform', loss_pct: 0, reorder_pct: 0, duplicate_pct: 0, direction: 'to' },
  port: null,
  ban_s: 60,
  hold: false,
  hold_s: 20,
}

/** The request for the chosen fault, with only its own fields; null until a target and a fault are chosen. */
export function faultRequest(d: FaultDraft): FaultIn | null {
  if (d.target === null || d.kind === null) return null
  const base = { kind: d.kind, target: d.target }
  const hold = { hold_s: d.hold ? d.hold_s : null }
  switch (d.kind) {
    case 'block':
      return d.flow === null ? null : { ...base, flow: d.flow, loss: d.loss, ...hold }
    case 'netem':
      return { ...base, netem: d.netem, ...hold }
    case 'link_down':
      return { ...base, port: d.port, ...hold }
    case 'ban':
      return { ...base, ban_s: d.ban_s }
    case 'deauth':
      return base
    default:
      return { ...base, ...hold }
  }
}

/** When a held fault ends, on the router's clock: "until cleared" or "clears in 42 s". */
export function untilText(until: string | null, now: Date): string {
  if (until === null) return 'until cleared'
  const left = Math.ceil((new Date(until).getTime() - now.getTime()) / 1000)
  return left > 0 ? `clears in ${left} s` : 'clearing now'
}
