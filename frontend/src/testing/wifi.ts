import type { ApplyResult, OptionRow, PlanOut, RadioState, Station, WifiState } from '../api/types'

export const AP2_RADIO: RadioState = {
  name: 'radio0',
  band: '2g',
  up: false,
  disabled: true,
  limits: {
    band: '2g',
    phy: 'phy0',
    max_htmode: 'HT40',
    channels: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
    txpower_dbm: Array.from({ length: 21 }, (_, i) => i),
    mcs: [0, 1, 2, 3, 4, 5, 6, 7],
    country: 'IL',
    sae: true,
  },
  modes: { kind: 'auto', modes: [] },
  channels: { kind: 'none', channels: [] },
  txpower: { kind: 'auto', dbm: null },
  legacy_rates: true,
  actual: null,
  mask: 'none',
  ssids: [{ section: 'default_radio0', ifname: null, ssid: 'OpenWrt', security: 'wpa2', encryption: 'psk2', key_set: true }],
  writers: { country: 'dima_night', cell_density: 'dima_night', legacy_rates: 'dima_night' },
}

export const AP2_WIFI: WifiState = { router_id: 'ap2', read_at: '2026-11-05T09:00:00', radios: [AP2_RADIO] }

export const N20_CH6_PLAN: PlanOut = {
  router_id: 'ap2',
  radio: 'radio0',
  lines: [
    "uci set wireless.radio0.htmode='HT20'",
    "uci set wireless.radio0.channel='6'",
    "uci set wireless.radio0.disabled='0'",
    'uci commit wireless',
    'wifi down radio0; wifi up radio0',
    'iw dev <AP interface of radio0> set bitrates legacy-2.4 6 ht-mcs-2.4 0 1 2 3 4 5 6 7',
  ],
  warnings: ['OpenWrt is already on air on AP1 · bench. The bench rule is one radio on air per SSID.'],
  expect: { radio_up: true, channels: [6], widths: [20], no_ht: false, txpower_dbm: null, beacon_mbps: 6 },
  digest: '5c1e0a9d7b3f2e41',
}

export const PROVEN: ApplyResult = {
  router_id: 'ap2',
  radio: 'radio0',
  applied: true,
  verified: true,
  error: null,
  checks: [
    { name: 'radio', ok: true, detail: 'up on phy0-ap0' },
    { name: 'channel', ok: true, detail: 'channel 6' },
    { name: 'width', ok: true, detail: '20 MHz' },
    { name: 'TX power', ok: true, detail: 'auto, actual 20.00 dBm' },
    { name: 'TX mask', ok: true, detail: 'legacy-2.4 6 ht-mcs-2.4 0 1 2 3 4 5 6 7' },
    { name: 'beacon rate', ok: true, detail: '6.0 Mb/s ×5' },
  ],
}

export const PANEL: Station = {
  mac: 'f4:12:fa:f3:57:68',
  ifname: 'phy0-ap0',
  ssid: 'OpenWrt',
  name: 'panel',
  ip: '192.168.1.30',
  signal_dbm: -52,
  tx_mbps: 65,
  tx_mcs: 7,
  rx_mbps: 54,
  mode: '802.11n 20',
  connected_s: 11520,
  inactive_ms: 40,
}

export const OPTIONS: OptionRow[] = [
  { group: 'device', section: 'radio0', name: 'htmode', type: 'string', editor: 'text', value: 'HT40', set_in_config: true, control: 'Modes', writer: null },
  { group: 'device', section: 'radio0', name: 'cell_density', type: 'uinteger', editor: 'number', value: '0', set_in_config: true, control: null, writer: 'dima_night' },
  { group: 'device', section: 'radio0', name: 'beacon_int', type: 'uinteger', editor: 'number', value: null, set_in_config: false, control: null, writer: null },
  { group: 'device', section: 'radio0', name: 'noscan', type: 'bool', editor: 'switch', value: null, set_in_config: false, control: 'Modes', writer: null },
  { group: 'interface', section: 'default_radio0', name: 'key', type: '<hidden>', editor: 'secret', value: null, set_in_config: true, control: 'Security (hidden)', writer: null },
]
