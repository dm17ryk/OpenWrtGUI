import { expect, test } from 'vitest'
import { nativeScreen } from './pages'

test('Status › Channel analysis opens RF live', () => {
  expect(nativeScreen('rf', 'ap2')).toEqual({ label: 'RF live › Channel analysis', to: '/routers/ap2/rf' })
})
