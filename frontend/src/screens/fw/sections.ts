import type { FirewallConf } from '../../api/types'
import { HELP } from '../../help/topics'

export type Kind = 'rule' | 'redirect' | 'nat' | 'ipset'
type FieldType = 'text' | 'list' | 'lines' | 'zone' | 'select'
export type Field = { key: string; label: string; type: FieldType; options?: readonly string[]; optional?: boolean }
export type Conf = FirewallConf['rules'][number] | FirewallConf['redirects'][number] | FirewallConf['nats'][number] | FirewallConf['ipsets'][number]
export type Draft = { values: Record<string, string>; enabled: boolean; others: Array<[string, string]> }
type Request = Record<string, unknown>

type KindSpec = { path: string; title: string; one: string; add: string; help: string; fields: readonly Field[]; defaults: Record<string, string> }

export const KINDS: Record<Kind, KindSpec> = {
  rule: {
    path: 'rules',
    title: 'Traffic rules',
    one: 'rule',
    add: '+ Rule',
    help: HELP.fwRules,
    defaults: { family: 'any', target: 'ACCEPT' },
    fields: [
      { key: 'name', label: 'Name', type: 'text' },
      { key: 'src', label: 'Source zone', type: 'zone', optional: true },
      { key: 'dest', label: 'Destination zone', type: 'zone', optional: true },
      { key: 'proto', label: 'Protocol', type: 'text', optional: true },
      { key: 'src_ip', label: 'Source address', type: 'list' },
      { key: 'src_port', label: 'Source port', type: 'text', optional: true },
      { key: 'dest_ip', label: 'Destination address', type: 'list' },
      { key: 'dest_port', label: 'Destination port', type: 'text', optional: true },
      { key: 'icmp_type', label: 'ICMP type', type: 'list' },
      { key: 'family', label: 'Family', type: 'select', options: ['any', 'ipv4', 'ipv6'] },
      { key: 'target', label: 'Action', type: 'select', options: ['ACCEPT', 'REJECT', 'DROP'] },
    ],
  },
  redirect: {
    path: 'forwards',
    title: 'Port forwards',
    one: 'port forward',
    add: '+ Port forward',
    help: HELP.fwForwards,
    defaults: { src: 'wan', dest: 'lan', proto: 'tcp udp' },
    fields: [
      { key: 'name', label: 'Name', type: 'text' },
      { key: 'proto', label: 'Protocol', type: 'text' },
      { key: 'src', label: 'From zone', type: 'zone' },
      { key: 'src_dport', label: 'External port', type: 'text' },
      { key: 'dest_ip', label: 'To device', type: 'text' },
      { key: 'dest_port', label: 'Internal port', type: 'text', optional: true },
      { key: 'dest', label: 'To zone', type: 'zone' },
    ],
  },
  nat: {
    path: 'nat',
    title: 'NAT rules',
    one: 'NAT rule',
    add: '+ NAT rule',
    help: HELP.fwNat,
    defaults: { src: 'wan', target: 'SNAT' },
    fields: [
      { key: 'name', label: 'Name', type: 'text' },
      { key: 'src', label: 'Zone', type: 'zone' },
      { key: 'src_ip', label: 'Source', type: 'text', optional: true },
      { key: 'dest_ip', label: 'Destination', type: 'text', optional: true },
      { key: 'dest_port', label: 'Destination port', type: 'text', optional: true },
      { key: 'proto', label: 'Protocol', type: 'text', optional: true },
      { key: 'target', label: 'Action', type: 'select', options: ['SNAT', 'MASQUERADE', 'ACCEPT'] },
      { key: 'snat_ip', label: 'Rewrite to', type: 'text', optional: true },
      { key: 'snat_port', label: 'Rewrite port', type: 'text', optional: true },
    ],
  },
  ipset: {
    path: 'ipsets',
    title: 'IP sets',
    one: 'IP set',
    add: '+ IP set',
    help: HELP.fwIpsets,
    defaults: { family: 'ipv4', match: 'src_ip' },
    fields: [
      { key: 'name', label: 'Name', type: 'text' },
      { key: 'family', label: 'Family', type: 'select', options: ['ipv4', 'ipv6'] },
      { key: 'match', label: 'Match', type: 'list' },
      { key: 'entries', label: 'Entries (one per line)', type: 'lines' },
    ],
  },
}

export function sectionsOf(kind: Kind, conf: FirewallConf): readonly Conf[] {
  return kind === 'rule' ? conf.rules : kind === 'redirect' ? conf.redirects : kind === 'nat' ? conf.nats : conf.ipsets
}

/** The empty state: what such an entry does on this router. */
export function emptyText(kind: Kind, short: string, conf: FirewallConf): string {
  if (kind === 'rule') return `No traffic rules on ${short}.`
  if (kind === 'redirect') return `No port forwards on ${short}. A port forward sends traffic arriving on wan to a device on lan.`
  if (kind === 'ipset') return `No IP sets on ${short}. A set is a named list of addresses, MACs or ports that rules can match in one go, for example all panel MACs.`
  const masq = conf.zones.find((z) => z.masq)
  const beyond = masq ? ` beyond ${masq.name} masquerading (set on the zone)` : ''
  return `No NAT rules on ${short}${beyond}. Use these for SNAT to a fixed address or to skip NAT for a subnet.`
}

export function draftOf(kind: Kind, conf: Conf | null): Draft {
  const spec = KINDS[kind]
  if (conf === null) return { values: { ...spec.defaults }, enabled: true, others: [] }
  const source = conf as unknown as Record<string, unknown>
  const values: Record<string, string> = {}
  for (const f of spec.fields) {
    const v = source[f.key]
    values[f.key] = Array.isArray(v) ? v.join(f.type === 'lines' ? '\n' : ', ') : v == null ? (f.key === 'family' && kind === 'rule' ? 'any' : '') : String(v)
  }
  return { values, enabled: conf.enabled, others: Object.entries(conf.others ?? {}) }
}

/** The other options that changed: new or edited values, and null for the ones removed. */
export function othersChange(before: Record<string, string> | undefined, rows: ReadonlyArray<readonly [string, string]>): Record<string, string | null> {
  const was = before ?? {}
  const out: Record<string, string | null> = {}
  for (const [k, v] of rows) if (k && was[k] !== v) out[k] = v
  for (const k of Object.keys(was)) if (!rows.some(([n]) => n === k)) out[k] = null
  return out
}

/** One upsert as the API takes it (TrafficRuleIn, ForwardIn, NatIn, IpsetIn). */
export function requestOf(kind: Kind, was: Conf | null, d: Draft): Request {
  const out: Request = { section: was?.section ?? null }
  for (const f of KINDS[kind].fields) {
    const v = (d.values[f.key] ?? '').trim()
    if (f.type === 'list') out[f.key] = v.split(/[\s,]+/).filter(Boolean)
    else if (f.type === 'lines') out[f.key] = v.split('\n').map((x) => x.trim()).filter(Boolean)
    else out[f.key] = v === '' && (f.optional || f.type === 'zone') ? null : v
  }
  return { ...out, enabled: d.enabled, others: othersChange(was?.others, d.others) }
}

export function sameRequest(kind: Kind, was: Conf, d: Draft): boolean {
  return JSON.stringify(requestOf(kind, was, d)) === JSON.stringify(requestOf(kind, was, draftOf(kind, was)))
}

export const isPin = (conf: Conf): boolean => conf.section.startsWith('owg_pin_')
