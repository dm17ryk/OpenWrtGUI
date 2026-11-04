import { expect, test } from 'vitest'
import { helpFor, parseManual, plainBlocks, slug, WIKI } from './manual'
import { HELP } from './topics'

test('anchors are the ones GitHub makes for wiki headings', () => {
  expect(slug('Air map')).toBe('air-map')
  expect(slug('3. Log in to the router')).toBe('3-log-in-to-the-router')
  expect(slug("4. Install the app's key")).toBe('4-install-the-apps-key')
  expect(slug('5. What is this router, and its sockets')).toBe('5-what-is-this-router-and-its-sockets')
  expect(slug('"The host key of 192.168.1.x changed"')).toBe('the-host-key-of-1921681x-changed')
})

test('markdown becomes plain sentences and bullets', () => {
  const md = [
    'Use **Check now**, see [Updating](Updating) and `C:\\Essence_SC`.',
    '![Shot](https://example.com/x.png)',
    '',
    '- **Solid bar**: the radio is up,',
    '  with its width.',
    '1. **The app key.** Already there.',
    '',
    '| Badge | Meaning |',
    '|---|---|',
    '| **on air** | At least one radio is up |',
    '',
    '```',
    'not shown',
    '```',
  ].join('\n')
  expect(plainBlocks(md)).toEqual([
    'Use Check now, see Updating and C:\\Essence_SC.',
    '• Solid bar: the radio is up, with its width.',
    '1. The app key. Already there.',
    '• on air: At least one radio is up',
  ])
})

test('a page gives its intro under the page name and each section under its anchor', () => {
  const help = parseManual({
    Dashboard: '# Dashboard\n\nShows every router.\n\n## Air map\n\nOne map per band.\n\n## Headline\n\nCounts the bench.\n',
  })
  expect(help.get('Dashboard')).toEqual({ title: 'Dashboard', blocks: ['Shows every router.'], url: `${WIKI}Dashboard` })
  expect(help.get('Dashboard#air-map')).toEqual({ title: 'Air map', blocks: ['One map per band.'], url: `${WIKI}Dashboard#air-map` })
  expect(help.get('Dashboard#headline')?.blocks).toEqual(['Counts the bench.'])
})

test('a heading inside a code block is not a section, and a repeated heading gets -1 like on GitHub', () => {
  const help = parseManual({
    Page: '# Page\n\n## Notes\n\nFirst.\n\n```\n## not a heading\n```\n\n## Notes\n\nSecond.\n',
  })
  expect([...help.keys()]).toEqual(['Page#notes', 'Page#notes-1'])
  expect(help.get('Page#notes')?.blocks).toEqual(['First.'])
  expect(help.get('Page#notes-1')?.blocks).toEqual(['Second.'])
})

test('long sections are cut after a few blocks', () => {
  const long = Array.from({ length: 8 }, (_, i) => `Sentence number ${i} is here to make the section long enough.`).join('\n\n')
  const blocks = parseManual({ Page: `# Page\n\n## Long\n\n${long}\n` }).get('Page#long')?.blocks ?? []
  expect(blocks.length).toBeLessThan(8)
  expect(blocks.at(-1)).toMatch(/…$/)
})

test.each(Object.entries(HELP))('help topic %s is a section of the manual', (_name, topic) => {
  const entry = helpFor(topic)
  expect(entry, topic).toBeDefined()
  expect(entry?.blocks.length).toBeGreaterThan(0)
  expect(entry?.url).toBe(WIKI + topic)
})
