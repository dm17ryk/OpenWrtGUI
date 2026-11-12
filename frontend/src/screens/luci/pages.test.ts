import { expect, test } from 'vitest'
import { nativeScreen } from './pages'

test('Status › Channel analysis opens RF live', () => {
  expect(nativeScreen('rf', 'ap2')).toEqual({ label: 'RF live › Channel analysis', to: '/routers/ap2/rf' })
})

test('RF live is named by the page it replaces', () => {
  expect(nativeScreen('rf', 'ap2', 'admin/status/channel_analysis')).toEqual({ label: 'RF live › Channel analysis', to: '/routers/ap2/rf' })
  expect(nativeScreen('rf', 'ap2', 'admin/status/realtime/wireless')).toEqual({ label: 'RF live', to: '/routers/ap2/rf' })
})
