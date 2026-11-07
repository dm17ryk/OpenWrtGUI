import { expect, test } from 'vitest'
import { uptimeText } from './rows'

test('uptime reads in the largest two units', () => {
  expect(uptimeText(42)).toBe('< 1 min')
  expect(uptimeText(14 * 60 + 5)).toBe('14 min')
  expect(uptimeText(2 * 3600 + 14 * 60)).toBe('2 h 14 min')
  expect(uptimeText(1786039)).toBe('20 d 16 h')
})
