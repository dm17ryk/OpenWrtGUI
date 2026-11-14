import { expect, test } from 'vitest'
import { nativeScreen } from './pages'

test('Status › Channel analysis opens RF live', () => {
  expect(nativeScreen('rf', 'ap2')).toEqual({ label: 'RF live › Channel analysis', to: '/routers/ap2/rf' })
})

test('RF live is named by the page it replaces', () => {
  expect(nativeScreen('rf', 'ap2', 'admin/status/channel_analysis')).toEqual({ label: 'RF live › Channel analysis', to: '/routers/ap2/rf' })
  expect(nativeScreen('rf', 'ap2', 'admin/status/realtime/wireless')).toEqual({ label: 'RF live', to: '/routers/ap2/rf' })
})

test('opens the tab a native page names', () => {
  expect(nativeScreen('system', 'ap2', 'admin/system/leds', 'leds')).toEqual({ label: 'System › LEDs', to: '/routers/ap2/system?tab=leds' })
  expect(nativeScreen('firewall', 'ap2', 'admin/network/firewall/rules', 'rules')).toEqual({ label: 'Firewall › Traffic rules', to: '/routers/ap2/firewall?tab=rules' })
  expect(nativeScreen('wifi', 'ap2', 'admin/network/wireless', null)).toEqual({ label: 'Wi-Fi', to: '/routers/ap2/wifi' })
})
