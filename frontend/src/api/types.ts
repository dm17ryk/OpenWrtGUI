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
