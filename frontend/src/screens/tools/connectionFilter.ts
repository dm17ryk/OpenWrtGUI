import type { Connection } from '../../api/types'

export type Proto = 'all' | 'tcp' | 'udp' | 'icmp' | 'other'
export type ConnectionFilter = { text: string; proto: Proto; sipOnly: boolean }

const NAMED = new Set(['tcp', 'udp', 'icmp'])

function protoMatches(proto: string, wanted: Proto): boolean {
  const p = proto.toLowerCase()
  if (wanted === 'all') return true
  if (wanted === 'other') return !NAMED.has(p)
  return p === wanted
}

function endpointText(c: Connection): string {
  return [c.src, c.sport, c.dst, c.dport].filter((v) => v !== null && v !== undefined).join(' ')
}

/** Tools › Connections' filters (v1.2a R8): run in the page over the rows read. */
export function matches(c: Connection, filter: ConnectionFilter): boolean {
  if (!protoMatches(c.proto, filter.proto)) return false
  if (filter.sipOnly && c.helper !== 'sip') return false
  const text = filter.text.trim()
  return text === '' || endpointText(c).includes(text)
}

/** Entries per protocol, the most first, then by name. */
export function byProtocol(rows: readonly Connection[]): Array<[string, number]> {
  const counts = new Map<string, number>()
  for (const c of rows) counts.set(c.proto, (counts.get(c.proto) ?? 0) + 1)
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
}
