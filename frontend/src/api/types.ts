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
export type OptionEditIn = S['OptionEditIn']
export type OptionsIn = S['OptionsIn']
export type RadioRequestIn = S['RadioRequestIn']
export type SsidIn = S['SsidIn']
export type Mode = ModesIn['modes'][number]
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
