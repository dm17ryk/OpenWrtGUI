import type { FwRuleConf, RuleView } from '../../api/types'
import { DIRECTIONS } from './model'

/** "wan → to this router", "lan → wan", or the zones as fw4 has them when the rule has no direction. */
export function ruleWhere(rule: RuleView): string {
  const { src, dest } = rule.conf
  if (rule.direction === 'forward') return `${src} → ${dest}`
  const d = DIRECTIONS.find((x) => x.id === rule.direction)
  if (d && rule.zone) return `${rule.zone} → ${d.short}`
  return `${src ?? 'any'} → ${dest ?? 'this router'}`
}

/** The match in a few words: addresses, protocol, ports, ICMP types. */
export function ruleMatch(conf: FwRuleConf): string {
  const parts: string[] = []
  if (conf.src_ip.length) parts.push(`from ${conf.src_ip.join(', ')}`)
  if (conf.dest_ip.length) parts.push(`to ${conf.dest_ip.join(', ')}`)
  const proto = [conf.proto ?? '', conf.icmp_type.join(', '), conf.src_port ? `sport ${conf.src_port}` : '', conf.dest_port ?? '']
    .filter(Boolean)
    .join(' ')
  if (proto) parts.push(proto)
  return parts.join(' · ') || 'any'
}

export function ruleAction(target: string): { label: string; cls: string } {
  return { label: target.toLowerCase(), cls: target === 'ACCEPT' ? 'acc' : target === 'REJECT' || target === 'DROP' ? 'rej' : 'neu' }
}
