import type { OptionRow } from '../api/types'

export const optionKey = (r: { section: string; name: string }): string => `${r.section}.${r.name}`

/** The edits as the API takes them: "" removes the option, a list option's words become its items. */
export function editsBody(
  edits: Record<string, string>,
  rows: OptionRow[],
): { section: string; name: string; value: string | string[] | null }[] {
  return Object.entries(edits).map(([key, raw]) => {
    const row = rows.find((r) => optionKey(r) === key)
    const [section, ...rest] = key.split('.')
    const value = raw === '' ? null : row?.editor === 'list' ? raw.split(/\s+/).filter(Boolean) : raw
    return { section, name: rest.join('.'), value }
  })
}
