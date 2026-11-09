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
export type LuciPageView = S['PageView']
export type BridgeView = S['BridgeView']
export type BridgeClosed = S['BridgeClosed']
export type UciChange = S['UciChange']
export type Mode = ModesIn['modes'][number]

// Network & DHCP, Ports (v0.3)
export type NetworkState = S['NetworkState']
export type InterfaceView = S['InterfaceView']
export type InterfaceConf = S['InterfaceConf']
export type ProtoView = S['ProtoView']
export type NetPlan = S['NetPlanOut']
export type NetApplyResult = S['NetApplyResult']
export type NetCheck = S['NetCheck']
export type DhcpConf = S['DhcpConf']
export type HostConf = S['HostConf']
export type Lease = S['Lease']
export type AccessState = S['AccessState']
export type SsidAccess = S['SsidAccess']
export type AccessDevice = S['AccessDevice']
export type DnsConf = S['DnsConf']
export type RouteConf = S['RouteConf']
export type RuleConf = S['RuleConf']
export type LiveTables = S['LiveTables']
export type PortsState = S['PortsState']
export type PortView = S['PortView']
export type VlanView = S['VlanView']
export type WifiMirror = S['WifiMirror']
// Request bodies: the schema marks fields that have a default as required; the server fills them in.
type Body<T, Required extends keyof T> = Partial<T> & Pick<T, Required>
export type InterfaceIn = Body<S['InterfaceIn'], 'name'>
export type DhcpIn = Body<S['DhcpIn'], 'interface'>
export type HostIn = Body<S['HostIn'], 'mac'>
export type HostsIn = { upserts: HostIn[]; deletes: string[] }
export type DnsIn = Partial<S['DnsIn']>
export type RouteIn = Body<S['RouteIn'], 'interface' | 'target'>
export type RuleIn = Partial<S['RuleIn']>
export type AccessIn = Body<S['AccessIn'], 'kind' | 'sections'>
export type VlanIn = Body<S['VlanIn'], 'vlan' | 'members'>
export type VlansIn = { upserts: VlanIn[]; deletes: string[] }
export type MirrorIn = Partial<S['MirrorIn']>
export type PortEnableIn = Partial<S['PortEnableIn']>

// Firewall, Faults and capture (v0.4)
export type FirewallState = S['FirewallState']
export type FirewallConf = S['FirewallConf']
export type ZoneConf = S['ZoneConf']
export type FwRuleConf = S['FwRuleConf']
export type RedirectConf = S['RedirectConf']
export type NatConf = S['NatConf']
export type IpsetConf = S['IpsetConf']
export type RuleView = S['RuleView']
export type PinView = S['PinView']
export type NftObject = S['NftObject']
export type TcHook = S['TcHook']
export type CustomFile = S['CustomFile']
export type Policy = ZoneConf['input']
export type ModelIn = Body<S['ModelIn'], 'cells'>
export type ZoneIn = Body<S['ZoneIn'], 'name' | 'input' | 'output' | 'forward'>
export type ZonesIn = { upserts: ZoneIn[]; deletes: string[]; forwardings?: S['ForwardingIn'][] | null }
export type TrafficRuleIn = Body<S['TrafficRuleIn'], 'name'>
export type ForwardIn = Body<S['ForwardIn'], 'name' | 'src_dport' | 'dest_ip'>
export type NatIn = Body<S['NatIn'], 'name' | 'src'>
export type IpsetIn = Body<S['IpsetIn'], 'name' | 'match'>
export type CustomIn = Body<S['CustomIn'], 'name'>
export type TableIn = Body<S['TableIn'], 'action'>
export type FaultsState = S['FaultsState']
export type FaultTarget = S['FaultTarget']
export type ArmedFault = S['ArmedFault']
export type FaultCaps = S['FaultCaps']
export type FaultIn = Body<S['FaultIn'], 'kind' | 'target'>
export type NetemIn = Partial<S['NetemIn']>
export type ClearIn = { ids: string[] | null }
export type CaptureView = S['CaptureView']
export type CaptureIn = Body<S['CaptureIn'], 'device'>
export type CaptureDevices = S['CaptureDevicesOut']
export type KnownDevice = S['KnownDevice']
export type KnownTable = S['KnownTable']

// Discovery and images (v0.5)
export type ProfileOut = S['ProfileOut']
export type ProfileKey = S['ProfileKey']
export type DiscoveryState = S['DiscoveryState']
export type DiscoverySummary = S['DiscoverySummary']
export type FirmwareCheck = S['FirmwareCheck']
export type OverlayEntry = S['OverlayEntry']
export type ConfigDiff = S['ConfigDiff']
export type CustomRow = S['CustomRow']
export type ProgramRow = S['ProgramRow']
export type ServiceRow = S['ServiceRow']
export type ChecklistInfo = S['ChecklistInfo']
export type ToolCard = S['ToolCard']
export type ToolCommand = S['ToolCommand']
export type ToolParam = S['ToolParam']
export type HelpResult = S['HelpResult']
export type FlashJob = S['FlashJob']
export type FlashPlanOut = S['FlashPlanOut']
export type CopyIn = Body<S['CopyIn'], 'paths' | 'target'>

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
export type LteState = S['LteState']
export type LteMeasure = S['Measure']
export type ModemInfo = S['ModemInfo']
export type AtResult = S['AtResult']
export type LteSettingsIn = S['LteSettingsIn']
export type LteAction = S['ActionIn']['action']
export type LteSample = {
  t: number
  rssi: number | null
  rsrp: number | null
  rsrq: number | null
  snr: number | null
  registration: string | null
  radio: string | null
}
/** Messages on /ws/lte/{router}. */
export type LteMessage = { type: 'lte'; sample: LteSample } | { type: 'lte-idle'; reason: string }
export type SystemOverview = S['SystemOverview']
export type LogEntry = S['LogEntry']
export type ProcessList = S['ProcessList']
export type ProcessRow = S['ProcessRow']
export type SystemServiceRow = S['SystemServiceRow']
export type ServiceAction = S['SystemServiceIn']['action']
export type Connections = S['Connections']
export type Connection = S['Connection']
export type TimeZones = S['TimeZones']
export type SystemSettingsOut = S['SettingsOut']
export type SystemSettingsIn = S['SettingsIn']
export type CronState = S['CronState']
export type CronTask = S['CronTask']
export type RebootJob = S['RebootJob']
export type BackupFile = S['BackupFile']
export type DiagResult = S['DiagResult']
export type DiagTool = S['DiagnoseIn']['tool']
export type SystemSample = {
  t: number
  load1: number | null
  load5: number | null
  load15: number | null
  connections: number | null
  /** interface -> [rx, tx] bytes per second since the last sample */
  rates: Record<string, [number, number]>
}
/** Messages on /ws/system/{router}. */
export type SystemMessage = { type: 'system'; sample: SystemSample } | { type: 'system-idle'; reason: string }
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
