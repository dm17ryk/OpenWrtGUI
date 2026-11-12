import type { Mode, RadioState, Security } from '../../api/types'

export const MODES: Mode[] = ['b', 'g', 'n20', 'n40']
export const MODE_LABEL: Record<Mode, string> = { b: '802.11b', g: '802.11g', n20: '802.11n · 20 MHz', n40: '802.11n · 40 MHz' }

/** The body of POST …/wifi/preview and …/wifi/apply; fields left out keep the router's value. */
export type SsidIn = { section: string; ssid?: string; security?: Exclude<Security, 'other'>; key?: string }
export type RadioRequestIn = {
  radio: string
  modes?: { kind: 'auto' | 'all' | 'set'; modes?: Mode[] }
  channels?: { kind: 'auto' | 'all' | 'none' | 'set'; channels?: number[] }
  txpower?: { kind: 'auto' | 'fixed'; dbm?: number | null }
  ssids?: SsidIn[]
}

export type ModeDraft = { kind: 'auto' | 'all' | 'set' | 'custom'; modes: Mode[] }
export type ChannelDraft = { kind: 'auto' | 'all' | 'none' | 'set'; channels: number[] }
export type TxDraft = { kind: 'auto' | 'fixed'; dbm: number | null }
export type SsidDraft = { ssid: string; security: Security; key: string }
export type Draft = { modes: ModeDraft; channels: ChannelDraft; txpower: TxDraft; ssids: Record<string, SsidDraft> }

const sortModes = (modes: Mode[]): Mode[] => MODES.filter((m) => modes.includes(m))

export function draftFrom(radio: RadioState): Draft {
  const set = sortModes(radio.modes.modes as Mode[])
  const modes: ModeDraft =
    radio.modes.kind === 'set'
      ? set.length === MODES.length
        ? { kind: 'all', modes: [] }
        : { kind: 'set', modes: set }
      : { kind: radio.modes.kind, modes: [] }
  const channels: ChannelDraft = {
    kind: radio.channels.kind,
    channels: [...radio.channels.channels].sort((a, b) => a - b),
  }
  const txpower: TxDraft =
    radio.txpower.kind === 'fixed' ? { kind: 'fixed', dbm: radio.txpower.dbm ?? null } : { kind: 'auto', dbm: null }
  const ssids = Object.fromEntries(
    radio.ssids.map((s) => [s.section, { ssid: s.ssid, security: s.security, key: '' }]),
  ) as Record<string, SsidDraft>
  return { modes, channels, txpower, ssids }
}

const same = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b)

/** What to ask the router for: only the parts that differ from what it has (null: nothing). */
export function requestFrom(radio: RadioState, d: Draft): RadioRequestIn | null {
  const base = draftFrom(radio)
  const req: RadioRequestIn = { radio: radio.name }
  const restoreMask = radio.mask === 'missing'
  if (d.modes.kind !== 'custom' && (restoreMask || !same(d.modes, base.modes))) {
    req.modes = d.modes.kind === 'set' ? { kind: 'set', modes: sortModes(d.modes.modes) } : { kind: d.modes.kind }
  }
  if (!same(d.channels, base.channels)) {
    req.channels = d.channels.kind === 'set' ? { kind: 'set', channels: [...d.channels.channels].sort((a, b) => a - b) } : { kind: d.channels.kind }
  }
  if (!same(d.txpower, base.txpower)) {
    req.txpower = d.txpower.kind === 'fixed' ? { kind: 'fixed', dbm: d.txpower.dbm } : { kind: 'auto' }
  }
  const ssids: SsidIn[] = []
  for (const [section, s] of Object.entries(d.ssids)) {
    const was = base.ssids[section]
    const one: SsidIn = { section }
    if (was && s.ssid !== was.ssid) one.ssid = s.ssid
    if (was && s.security !== was.security && s.security !== 'other') one.security = s.security
    if (s.key) one.key = s.key
    if (Object.keys(one).length > 1) ssids.push(one)
  }
  if (ssids.length > 0) req.ssids = ssids
  return Object.keys(req).length > 1 ? req : null
}

export function modeSummary(d: ModeDraft): string {
  if (d.kind === 'auto') return 'Auto · router decides'
  if (d.kind === 'all') return 'All · b + g + n20 + n40'
  if (d.kind === 'custom') return 'Custom · set outside the selector'
  return d.modes.length === 0 ? 'nothing ticked' : `Only ${sortModes(d.modes).join(' + ')}`
}

export function channelSummary(d: ChannelDraft, allowed: number[]): string {
  if (d.kind === 'auto') return 'Auto · any allowed channel'
  if (d.kind === 'all') return `All · ${Math.min(...allowed)}–${Math.max(...allowed)}`
  if (d.kind === 'none') return 'None · radio parked'
  const chosen = [...d.channels].sort((a, b) => a - b)
  if (chosen.length === 0) return 'nothing ticked'
  return chosen.length === 1 ? `Fixed · ch ${chosen[0]}` : `Pick among ${chosen.join(', ')}`
}

export function widthText(d: ModeDraft): string {
  if (d.kind === 'auto' || d.kind === 'custom') return 'router default'
  const m = d.kind === 'all' ? MODES : d.modes
  if (m.includes('n40')) return m.includes('n20') ? 'HT40 · 20 MHz fallback' : 'HT40 · forced'
  return m.includes('n20') ? 'HT20' : 'legacy 20 MHz'
}

export const SECURITY_LABEL: Record<Security, string> = {
  open: 'Open',
  wpa2: 'WPA2-PSK',
  wpa3: 'WPA3-SAE',
  wpa2_wpa3: 'WPA2 + WPA3',
  other: 'Other (see All options)',
}
