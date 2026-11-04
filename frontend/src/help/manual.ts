/**
 * In-app help: sections of the user manual (docs/manual, published as the GitHub wiki), bundled at
 * build time so the help works offline and always matches the manual of this version.
 */

export const WIKI = 'https://github.com/dm17ryk/OpenWrtGUI/wiki/'

/** Enough text for a tooltip; the rest is one click away in the wiki. */
const MAX_CHARS = 320

export type HelpEntry = {
  title: string
  blocks: string[]
  url: string
}

/** The anchor GitHub gives a heading: lower case, punctuation dropped, spaces to hyphens. */
export function slug(heading: string): string {
  return heading
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s_-]/gu, '')
    .replace(/\s/g, '-')
}

function inline(text: string): string {
  // Code spans first, kept aside (as private-use characters), so `txlab_*.py` keeps its _ and *.
  const code: string[] = []
  const prose = text.replace(/`([^`]+)`/g, (_m, span: string) => `${code.push(span) - 1}`)
  return prose
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/(\*\*|__)(.+?)\1/g, '$2')
    .replace(/(^|[\s(])[*_](\S.*?)[*_](?=[\s).,:;!?]|$)/g, '$1$2')
    .replace(/(\d+)/g, (_m, i: string) => code[Number(i)])
    .replace(/\s+/g, ' ')
    .trim()
}

function tableRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\||\|$/g, '')
    .split('|')
    .map((cell) => inline(cell))
}

/** Paragraphs, list items (as "• …" or "1. …") and table rows ("• first: rest") as plain text. */
export function plainBlocks(markdown: string): string[] {
  const blocks: string[] = []
  const lines = markdown.split(/\r?\n/)
  let current: string[] = []
  let fenced = false
  const flush = (): void => {
    const text = inline(current.join(' '))
    if (text) blocks.push(text)
    current = []
  }
  lines.forEach((line, i) => {
    if (line.trim().startsWith('```')) {
      flush()
      fenced = !fenced
      return
    }
    if (fenced) return
    const trimmed = line.trim()
    if (!trimmed) return flush()
    if (trimmed.startsWith('|')) {
      flush()
      const separator = /^\|?\s*:?-{3,}/.test(trimmed)
      const header = /^\|?\s*:?-{3,}/.test(lines[i + 1]?.trim() ?? '')
      if (!separator && !header) {
        const [first, ...rest] = tableRow(trimmed)
        blocks.push(`• ${first}: ${rest.join(' · ')}`)
      }
      return
    }
    const bullet = /^[-*+]\s+(.*)$/.exec(trimmed)
    const numbered = /^(\d+)\.\s+(.*)$/.exec(trimmed)
    if (bullet || numbered) {
      flush()
      current = [bullet ? `• ${bullet[1]}` : `${numbered?.[1]}. ${numbered?.[2]}`]
      return
    }
    current.push(trimmed.replace(/^>\s?/, ''))
  })
  flush()
  return blocks
}

function clip(blocks: string[]): string[] {
  const kept: string[] = []
  let total = 0
  for (const block of blocks) {
    if (kept.length > 0 && total + block.length > MAX_CHARS) {
      kept[kept.length - 1] += ' …'
      return kept
    }
    kept.push(block)
    total += block.length
  }
  return kept
}

/**
 * Pages keyed by file name (`Dashboard`). Each page gives its intro under the page name and every
 * `##`/`###` section under `Page#anchor`, the same address the wiki uses.
 */
export function parseManual(pages: Record<string, string>): Map<string, HelpEntry> {
  const help = new Map<string, HelpEntry>()
  for (const [page, markdown] of Object.entries(pages)) {
    // A "## line" inside a code block is code, not a heading (plainBlocks skips code anyway).
    const parts = markdown.replace(/^```[\s\S]*?^```.*$/gm, '').split(/^(#{1,3}) +(.+)$/m)
    // parts: [before, hashes, heading, body, hashes, heading, body, ...]
    const seen = new Map<string, number>()
    for (let i = 1; i < parts.length; i += 3) {
      const [hashes, heading, body] = [parts[i], parts[i + 1].trim(), parts[i + 2] ?? '']
      // GitHub numbers repeated headings: notes, notes-1, notes-2.
      const base = slug(heading)
      const n = seen.get(base) ?? 0
      seen.set(base, n + 1)
      const blocks = clip(plainBlocks(body))
      if (blocks.length === 0) continue
      const topic = hashes === '#' ? page : `${page}#${n ? `${base}-${n}` : base}`
      help.set(topic, { title: hashes === '#' ? heading : inline(heading), blocks, url: WIKI + topic })
    }
  }
  return help
}

const RAW = import.meta.glob<string>('../../../docs/manual/*.md', { query: '?raw', import: 'default', eager: true })
const PAGES = Object.fromEntries(
  Object.entries(RAW).map(([path, text]) => [path.replace(/^.*\/([^/]+)\.md$/, '$1'), text]),
)
const MANUAL = parseManual(PAGES)

export function helpFor(topic: string): HelpEntry | undefined {
  return MANUAL.get(topic)
}
