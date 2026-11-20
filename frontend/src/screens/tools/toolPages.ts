/** The Tools screen's pages (spec 7.8 Phase 2, v1.2a R2), in tab order. 1.2b appends its active pages. */
export const TOOL_PAGES = [
  { key: 'port-stats', label: 'Port statistics' },
  { key: 'connections', label: 'Connections' },
] as const

export type ToolKey = (typeof TOOL_PAGES)[number]['key']

export function toolPage(key: string | undefined): ToolKey | null {
  return TOOL_PAGES.find((p) => p.key === key)?.key ?? null
}
