import { useState } from 'react'
import type { DhcpConf, DhcpIn, NetworkState } from '../../api/types'
import { Toggle } from '../../components/Toggle'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from './NetChange'
import { isBad, sameList, shortName, whole } from './rows'

const PRESETS: ReadonlyArray<readonly [string, string]> = [
  ['3', 'Router'],
  ['6', 'DNS servers'],
  ['15', 'Domain'],
  ['42', 'NTP servers'],
]
const V6_MODES = ['server', 'relay', 'hybrid', 'disabled'] as const
type V6Mode = (typeof V6_MODES)[number]
type OptionDraft = { code: string; value: string }
type Draft = { enabled: boolean; start: string; limit: string; leasetime: string; options: OptionDraft[]; dhcpv6: string; ra: string }

function draftOf(conf: DhcpConf | undefined): Draft {
  return {
    enabled: conf?.enabled ?? false,
    start: String(conf?.start ?? 100),
    limit: String(conf?.limit ?? 150),
    leasetime: conf?.leasetime ?? '12h',
    options: (conf?.options ?? []).map((o) => {
      const [code, ...rest] = o.split(',')
      return { code, value: rest.join(',') }
    }),
    dhcpv6: conf?.dhcpv6 ?? '',
    ra: conf?.ra ?? '',
  }
}

/** Only what changed from the router's config; null when nothing did, 'bad' when a number is not one. */
function dhcpRequest(iface: string, conf: DhcpConf | undefined, d: Draft): DhcpIn | null | 'bad' {
  const was = draftOf(conf)
  const start = whole(d.start)
  const limit = whole(d.limit)
  if (isBad(start) || isBad(limit)) return 'bad'
  const options = d.options.filter((o) => o.code.trim()).map((o) => `${o.code.trim()},${o.value.trim()}`)
  const req: DhcpIn = {
    interface: iface,
    ...(d.enabled !== was.enabled ? { enabled: d.enabled } : {}),
    ...(d.start !== was.start && start !== null ? { start } : {}),
    ...(d.limit !== was.limit && limit !== null ? { limit } : {}),
    ...(d.leasetime !== was.leasetime ? { leasetime: d.leasetime } : {}),
    ...(!sameList(options, conf?.options ?? []) ? { options } : {}),
    ...(d.dhcpv6 !== was.dhcpv6 && d.dhcpv6 ? { dhcpv6: d.dhcpv6 as V6Mode } : {}),
    ...(d.ra !== was.ra && d.ra ? { ra: d.ra as V6Mode } : {}),
  }
  return Object.keys(req).length > 1 ? req : null
}

type FormProps = { routerId: string; short: string; iface: string; conf: DhcpConf | undefined; onApplied: () => void }

function DhcpForm({ routerId, short, iface, conf, onApplied }: FormProps) {
  const [draft, setDraft] = useState(() => draftOf(conf))
  const set = (patch: Partial<Draft>): void => setDraft({ ...draft, ...patch })
  const setOption = (i: number, patch: Partial<OptionDraft>): void =>
    set({ options: draft.options.map((o, n) => (n === i ? { ...o, ...patch } : o)) })
  const req = dhcpRequest(iface, conf, draft)
  const change = usePlanApply(`/api/routers/${routerId}/network/dhcp`, req === 'bad' ? null : req, onApplied)
  const preset = (code: string): string => PRESETS.find(([c]) => c === code)?.[1] ?? 'option'
  const modeSelect = (name: 'dhcpv6' | 'ra', label: string) => (
    <label className="field">
      <span>{label}</span>
      <select className="in" aria-label={label} value={draft[name]} onChange={(e) => set({ [name]: e.target.value })}>
        {!V6_MODES.includes(draft[name] as V6Mode) && <option value="">not set</option>}
        {V6_MODES.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
    </label>
  )
  return (
    <>
      <Toggle label="DHCP server" checked={draft.enabled} onChange={(enabled) => set({ enabled })}>
        {draft.enabled ? `Hands out addresses on ${iface}` : `Off: ${iface} hands out no addresses`}
      </Toggle>
      <div className="grid">
        <label className="field">
          <span>Pool start</span>
          <input className="in mono" aria-label="Pool start" inputMode="numeric" value={draft.start} onChange={(e) => set({ start: e.target.value })} />
        </label>
        <label className="field">
          <span>Pool size</span>
          <input className="in mono" aria-label="Pool size" inputMode="numeric" value={draft.limit} onChange={(e) => set({ limit: e.target.value })} />
        </label>
        <label className="field">
          <span>Lease time</span>
          <input className="in mono" aria-label="Lease time" placeholder="12h" value={draft.leasetime} onChange={(e) => set({ leasetime: e.target.value })} />
        </label>
      </div>
      <div className="stack" style={{ gap: 6 }}>
        <div className="eyebrow">Options by code</div>
        {draft.options.map((o, i) => (
          <div className="row" key={i}>
            <input className="in mono" style={{ width: 70 }} aria-label={`Code of option ${i + 1}`} value={o.code} onChange={(e) => setOption(i, { code: e.target.value })} />
            <span className="muted">{preset(o.code.trim())}</span>
            <input className="in mono" aria-label={`Value of option ${i + 1}`} value={o.value} onChange={(e) => setOption(i, { value: e.target.value })} />
            <button className="btn" type="button" aria-label={`Remove option ${i + 1}`} onClick={() => set({ options: draft.options.filter((_, n) => n !== i) })}>
              Remove
            </button>
          </div>
        ))}
        <div className="row">
          {PRESETS.map(([code, label]) => (
            <button key={code} className="btn" type="button" onClick={() => set({ options: [...draft.options, { code, value: '' }] })}>
              + {code} {label}
            </button>
          ))}
          <button className="btn" type="button" onClick={() => set({ options: [...draft.options, { code: '', value: '' }] })}>
            + Any option by code
          </button>
        </div>
      </div>
      <div className="grid">
        {modeSelect('dhcpv6', 'DHCPv6')}
        {modeSelect('ra', 'RA')}
      </div>
      {req === 'bad' && <div className="note x">Pool start and size are whole numbers.</div>}
      <NetChange change={change} short={short} helpTopic={HELP.netDhcp} show={req !== null && req !== 'bad'} />
    </>
  )
}

type Props = { routerId: string; routerName: string; state: NetworkState; onApplied: () => void }

/** The DHCP server on one interface: on/off, pool, lease time, options by code, IPv6 (spec 7.4). */
export function DhcpCard({ routerId, routerName, state, onApplied }: Props) {
  const names = state.interfaces.flatMap((v) => (v.conf ? [v.conf.name] : []))
  const [iface, setIface] = useState(state.dhcp[0]?.interface ?? state.own_interface ?? names[0] ?? '')
  return (
    <section className="card stack" aria-labelledby="dhcp-h">
      <div className="row">
        <div className="hrow">
          <h2 id="dhcp-h">DHCP server</h2>
          <Help topic={HELP.netDhcp} />
        </div>
        <label className="row" style={{ gap: 6 }}>
          <span className="muted">on</span>
          <select className="in" aria-label="Interface" value={iface} onChange={(e) => setIface(e.target.value)}>
            {names.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>
      <DhcpForm
        key={iface}
        routerId={routerId}
        short={shortName(routerName, routerId)}
        iface={iface}
        conf={state.dhcp.find((d) => d.interface === iface)}
        onApplied={onApplied}
      />
    </section>
  )
}
