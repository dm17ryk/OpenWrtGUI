import { expect, test } from 'vitest'
import { AP1_FW, AP1_RULESET } from '../../testing/fw'
import { chainsOf, parseRuleset, ruleBody } from './nfttext'

test('the ruleset text becomes tables, chains with their declaration, and rules with packets', () => {
  const tables = parseRuleset(AP1_RULESET)
  expect(tables.map((t) => `${t.family} ${t.name}`)).toEqual(['inet fw4', 'bridge voipdscp', 'ip lab_scratch'])
  const [post] = tables[1].chains
  expect(post.name).toBe('post')
  expect(post.declaration).toBe('type filter hook postrouting priority 0; policy accept;')
  expect(post.rules).toEqual([
    { text: 'udp dport 5004 ip dscp set ef counter packets 31 bytes 6200', packets: 31 },
    { text: 'udp dport { 5060, 5061 } ip dscp set ef counter packets 0 bytes 0', packets: 0 },
  ])
  // a named set is carried by the backend; it is not a chain
  expect(tables[1].chains).toHaveLength(1)
})

test('a chain inside fw4 is found even when it is indented differently', () => {
  const guard = AP1_FW.objects.find((o) => o.chain === 'BENCHSIPGUARD')
  const chains = chainsOf(parseRuleset(AP1_RULESET), guard!)
  expect(chains.map((c) => c.name)).toEqual(['BENCHSIPGUARD'])
  expect(chains[0].declaration).toBeNull()
  expect(chains[0].rules.map((r) => r.packets)).toEqual([0, 7])
})

test('a rule is written back without its counter values', () => {
  expect(ruleBody('udp dport 5004 ip dscp set ef counter packets 31 bytes 6200')).toBe('udp dport 5004 ip dscp set ef counter')
  expect(ruleBody('  ip saddr 192.168.1.30 accept  ')).toBe('ip saddr 192.168.1.30 accept')
})
