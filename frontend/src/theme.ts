import type { Theme } from './api/types'

export type Resolved = 'light' | 'dark'

export function resolveTheme(setting: Theme, prefersDark: boolean): Resolved {
  if (setting === 'system') return prefersDark ? 'dark' : 'light'
  return setting
}

export function prefersDark(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function applyTheme(resolved: Resolved): void {
  document.documentElement.dataset.theme = resolved
}
