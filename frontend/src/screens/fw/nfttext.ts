import type { NftObject } from '../../api/types'

export type NftRule = { text: string; packets: number | null }
export type NftChain = { name: string; declaration: string | null; rules: NftRule[] }
export type NftTable = { family: string; name: string; chains: NftChain[] }

const HANDLE = /\s*# handle \d+$/
const TABLE = /^table (\S+) (\S+) \{$/
const CHAIN = /^chain (\S+) \{$/
const PACKETS = /counter packets (\d+) bytes \d+/

const net = (line: string): number => (line.match(/\{/g)?.length ?? 0) - (line.match(/\}/g)?.length ?? 0)

/**
 * `nft -a list ruleset` as tables of chains of rules (src/openwrtgui/fw/nft.py reads the same text). Named sets,
 * maps and other blocks are skipped: an edit carries them over as they are.
 */
export function parseRuleset(text: string): NftTable[] {
  const tables: NftTable[] = []
  let table: NftTable | null = null
  let chain: NftChain | null = null
  let skip = 0
  for (const raw of text.split('\n')) {
    const line = raw.replace(HANDLE, '').trim()
    if (!line) continue
    if (skip > 0) {
      skip += net(line)
      continue
    }
    if (table === null) {
      const m = TABLE.exec(line)
      if (m) table = { family: m[1], name: m[2], chains: [] }
      continue
    }
    if (chain === null) {
      const m = CHAIN.exec(line)
      if (m) {
        chain = { name: m[1], declaration: null, rules: [] }
        table.chains.push(chain)
      } else if (line === '}') {
        tables.push(table)
        table = null
      } else {
        skip = net(line)
      }
      continue
    }
    if (line === '}') chain = null
    else if (/^(type |policy )/.test(line)) chain.declaration = chain.declaration ? `${chain.declaration} ${line}` : line
    else {
      const counted = PACKETS.exec(line)
      chain.rules.push({ text: line, packets: counted ? Number(counted[1]) : null })
    }
  }
  return tables
}

/** The chains an object covers: every chain of its table, or the one fw4 chain a harness owns. */
export function chainsOf(tables: NftTable[], obj: NftObject): NftChain[] {
  const table = tables.find((t) => t.family === obj.family && t.name === obj.table)
  if (!table) return []
  return obj.chain ? table.chains.filter((c) => c.name === obj.chain) : table.chains
}

/** A listed rule as it is written back: counters without their values (fw/nft.py rule_text). */
export function ruleBody(text: string): string {
  return text.trim().replace(/counter packets \d+ bytes \d+/, 'counter')
}
