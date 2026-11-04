import { expect, test } from 'vitest'
import { applyTheme, resolveTheme } from './theme'

test('resolveTheme follows Windows only for system', () => {
  expect(resolveTheme('system', true)).toBe('dark')
  expect(resolveTheme('system', false)).toBe('light')
  expect(resolveTheme('light', true)).toBe('light')
  expect(resolveTheme('dark', false)).toBe('dark')
})

test('applyTheme sets data-theme on the root element', () => {
  applyTheme('dark')
  expect(document.documentElement.dataset.theme).toBe('dark')
})
