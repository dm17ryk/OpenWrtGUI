import type { components } from './schema'

type S = components['schemas']

export type AppKeyOut = S['AppKeyOut']
export type AuditEntry = S['AuditEntry']
export type DescriptionSummary = S['DescriptionSummary']
export type GuardOut = S['GuardOut']
export type GuardWatchList = S['GuardWatchList']
export type ReasonOut = S['ReasonOut']
export type RadioStatus = S['RadioStatus']
export type RouterDetail = S['RouterDetail']
export type RouterHealth = S['RouterHealth']
export type RouterItem = S['RouterItem']
export type RouterRecord = S['RouterRecord']
export type RouterStatus = S['RouterStatus']
export type SessionView = S['SessionView']
export type Settings = S['Settings']
export type StationInfo = S['StationInfo']
export type UpdateOut = S['UpdateOut']
export type Preview = S['Preview']
export type WifiState = S['WifiState']
export type RadioState = S['RadioState']
export type SsidState = S['SsidState']
export type RadioLimits = S['RadioLimits']
export type ModeSelection = S['ModeSelection']
export type ChannelSelection = S['ChannelSelection']
export type TxPowerSetting = S['TxPowerSetting']
export type PlanOut = S['PlanOut']
export type ApplyResult = S['ApplyResult']
export type Check = S['Check']
export type Station = S['Station']
export type OptionRow = S['OptionRow']
export type Mode = ModesIn['modes'][number]

// RF live (/ws/rf/{id}); WebSocket messages are not in the OpenAPI schema (src/openwrtgui/rf/sample.py).
export type Bitrate = { mbps: number; mcs: number | null; width_mhz: number; short_gi: boolean; mode: Mode }
export type RadioSample = {
  channel: number | null
  freq_mhz: number | null
  width_mhz: number | null
  txpower_dbm: number | null
  busy_pct: number | null
  noise_dbm: number | null
  ack_fail_per_s: number | null
}
export type StationSample = {
  mac: string
  name: string | null
  signal_dbm: number | null
  signal_avg_dbm: number | null
  chains: number[]
  rx: Bitrate | null
  tx: Bitrate | null
  rx_pps: number | null
  rx_kbps: number | null
  tx_pps: number | null
  tx_kbps: number | null
  retry_pct: number | null
  failed_per_s: number | null
  rx_drops: number | null
  inactive_ms: number | null
  expected_mbps: number | null
  ack_signal_dbm: number | null
}
export type RfSample = {
  at: string
  router_id: string
  radio: string
  ifname: string
  radio_sample: RadioSample
  stations: StationSample[]
  left: string[]
}
export type RateRow = { rate: string; mode: string; attempts: number; success_pct: number; in_use: boolean }
export type RfMessage =
  | { type: 'rf'; sample: RfSample }
  | { type: 'rf-idle'; reason: string }
  | { type: 'recording'; path: string | null }
  | { type: 'rates'; mac: string; rows?: RateRow[]; error?: string }
export type Security = SsidState['security']
type ModesIn = S['ModesIn']

export type Theme = Settings['theme']

/** Messages on /ws/live. */
export type LiveMessage =
  | { type: 'guard'; state: GuardOut }
  | { type: 'status'; router: string; status: RouterStatus }
  | { type: 'router-offline'; router: string; since: string; error: string | null }
  | { type: 'update'; status: UpdateOut }
  | { type: 'update-progress'; version: string; done: number; total: number }

/** Messages on /ws/terminal/{id}. */
export type TerminalMessage =
  | { type: 'mode'; mode: 'pty' | 'line' | 'line-available-pty'; reason: string | null }
  | { type: 'output'; data: string }
  | { type: 'refused'; line: string; reason: string }
  | { type: 'exit'; status: number }
  | { type: 'error'; detail: string }
export type AppInfo = S['AppInfo']
