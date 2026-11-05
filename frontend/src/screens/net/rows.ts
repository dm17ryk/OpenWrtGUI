/** Small helpers the Network cards share for their editable rows and lists. */

export const words = (text: string): string[] => text.split(/[\s,]+/).filter(Boolean)

/** '' → null; a whole number → it; anything else → NaN, which a card refuses before any preview. */
export function whole(text: string): number | null {
  const t = text.trim()
  if (t === '') return null
  return /^\d+$/.test(t) ? Number(t) : Number.NaN
}

export const isBad = (n: number | null): boolean => n !== null && Number.isNaN(n)

export const sameList = (a: readonly string[], b: readonly string[]): boolean => a.join('\n') === b.join('\n')

export const toggled = (list: readonly string[], item: string): string[] =>
  list.includes(item) ? list.filter((x) => x !== item) : [...list, item]

/** A table of config sections being edited: rows changed by section, sections to delete, new rows. */
export type RowSet<R> = { edited: Record<string, R>; deleted: string[]; added: R[] }

export const noRows = <R>(): RowSet<R> => ({ edited: {}, deleted: [], added: [] })

/** The rows to send: edited sections that differ from the router's (and are not being deleted), then new rows worth sending. */
export function upsertsOf<C extends { section: string }, R>(confs: readonly C[], rows: RowSet<R>, rowOf: (c: C) => R, isFilled: (r: R) => boolean): R[] {
  const edited = confs.flatMap((c) => {
    const row = rows.edited[c.section]
    return row && !rows.deleted.includes(c.section) && JSON.stringify(row) !== JSON.stringify(rowOf(c)) ? [row] : []
  })
  return [...edited, ...rows.added.filter(isFilled)]
}

/** A short router name for headings: "AP2 · office" → "AP2". */
export const shortName = (routerName: string, routerId: string): string => routerName.split(' · ')[0] || routerId

/** "59 min", "11 h 6 min"; null is a lease that never ends. */
export function expiresIn(seconds: number | null): string {
  if (seconds === null) return 'never'
  if (seconds < 60) return `${seconds} s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} min`
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`
}
