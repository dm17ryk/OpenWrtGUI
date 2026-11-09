import type { LteSettingsIn, OptionRow } from '../../api/types'

/** The settings request: every field optional (None on the server = leave as it is). */
export type SettingsBody = Partial<LteSettingsIn>
export type Auth = NonNullable<LteSettingsIn['auth']>
export type PdpType = NonNullable<LteSettingsIn['pdptype']>

export type SettingsDraft = {
  apn: string
  auth: Auth
  username: string
  password: string
  pincode: string
  pdptype: PdpType
  mtu: string
  metric: string
  auto: boolean
  defaultroute: boolean
}

/** The options the form lays out by hand; All options shows them read-only ("set above"). */
export const NAMED = new Set(['apn', 'auth', 'username', 'password', 'pincode', 'pdptype', 'metric', 'defaultroute'])
export const SET_ABOVE = 'Settings' // OptionsTable shows "set above: Settings"
const AUTHS: readonly Auth[] = ['none', 'pap', 'chap', 'both']
const PDP_TYPES: readonly PdpType[] = ['ipv4', 'ipv6', 'ipv4v6']

function text(rows: OptionRow[], name: string): string {
  const v = rows.find((r) => r.name === name)?.value
  return Array.isArray(v) ? v.join(' ') : (v ?? '')
}

function oneOf<T extends string>(value: string, allowed: readonly T[], fallback: T): T {
  return (allowed as readonly string[]).includes(value) ? (value as T) : fallback
}

/** The form as the router has it now; secrets always start empty (left empty = keep what the router has). */
export function initialDraft(rows: OptionRow[], auto: boolean): SettingsDraft {
  return {
    apn: text(rows, 'apn'),
    auth: oneOf(text(rows, 'auth'), AUTHS, 'none'),
    username: text(rows, 'username'),
    password: '',
    pincode: '',
    pdptype: oneOf(text(rows, 'pdptype'), PDP_TYPES, 'ipv4'),
    mtu: text(rows, 'mtu'),
    metric: text(rows, 'metric'),
    auto,
    defaultroute: text(rows, 'defaultroute') !== '0',
  }
}

/** All options with the hand-laid fields marked as set above, so each option has one control. */
export function optionRows(rows: OptionRow[]): OptionRow[] {
  return rows.map((r) => (NAMED.has(r.name) && !r.control ? { ...r, control: SET_ABOVE } : r))
}

const WHOLE = /^\d+$/

/** What changed, as the settings request; a number field that is not a whole number is an error. */
export function settingsBody(initial: SettingsDraft, draft: SettingsDraft): { body: SettingsBody; error: string | null } {
  const body: SettingsBody = {}
  if (draft.apn !== initial.apn) body.apn = draft.apn
  if (draft.auth !== initial.auth) body.auth = draft.auth
  if (draft.username !== initial.username) body.username = draft.username
  if (draft.password) body.password = draft.password
  if (draft.pincode) body.pincode = draft.pincode
  if (draft.pdptype !== initial.pdptype) body.pdptype = draft.pdptype
  if (draft.auto !== initial.auto) body.auto = draft.auto
  if (draft.defaultroute !== initial.defaultroute) body.defaultroute = draft.defaultroute
  for (const field of ['mtu', 'metric'] as const) {
    if (draft[field] === initial[field] || draft[field] === '') continue
    if (!WHOLE.test(draft[field])) return { body, error: `${field === 'mtu' ? 'MTU' : 'Metric'} is a whole number` }
    body[field] = Number(draft[field])
  }
  return { body, error: null }
}
