import { useState } from 'react'
import type { DnsConf, DnsIn, NetworkState } from '../../api/types'
import { Toggle } from '../../components/Toggle'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from './NetChange'
import { isBad, sameList, shortName, whole, words } from './rows'

/** dnsmasq's on/off options (src/openwrtgui/net/dns.py DNS_SWITCHES), in words. */
const SWITCHES: ReadonlyArray<readonly [string, string]> = [
  ['domainneeded', "Don't forward plain names"],
  ['boguspriv', "Don't forward private reverse lookups"],
  ['localise_queries', 'Answer with the address of the asking interface'],
  ['logqueries', 'Log every query'],
  ['localservice', 'Answer local subnets only'],
]
const REBIND: ReadonlyArray<readonly [string, string]> = [
  ['rebind_protection', 'Rebind protection: drop private addresses in upstream answers'],
  ['rebind_localhost', 'Allow 127.0.0.0/8 answers (for DNS block lists)'],
]
const HAND_LAID = new Set(['server', 'domain', 'local', 'rebind_domain', 'address', 'cachesize', ...[...SWITCHES, ...REBIND].map(([n]) => n)])

type Override = { host: string; ip: string }
type Other = { name: string; value: string; removed: boolean; isNew: boolean }
type Draft = { forwarders: string; domain: string; rebind: string; overrides: Override[]; switches: Record<string, boolean>; cachesize: string; others: Other[] }

function overrideOf(item: string): Override {
  const parts = item.split('/').filter(Boolean)
  return { host: parts.slice(0, -1).join('/'), ip: parts.at(-1) ?? '' }
}

function draftOf(dns: DnsConf): Draft {
  const v = dns.values ?? {}
  return {
    forwarders: words(v.server ?? '').join(' '),
    domain: v.domain ?? '',
    rebind: words(v.rebind_domain ?? '').join(' '),
    overrides: words(v.address ?? '').map(overrideOf),
    switches: Object.fromEntries([...SWITCHES, ...REBIND].map(([n]) => [n, v[n] === '1'])),
    cachesize: v.cachesize ?? '',
    others: Object.entries(v)
      .filter(([k]) => !HAND_LAID.has(k))
      .map(([name, value]) => ({ name, value, removed: false, isNew: false })),
  }
}

const overrideList = (list: Override[]): string[] => list.filter((o) => o.host.trim() || o.ip.trim()).map((o) => `/${o.host.trim()}/${o.ip.trim()}`)

/** Only what changed; null when nothing did, 'bad' when the cache size is not a whole number. */
function dnsRequest(dns: DnsConf, d: Draft): DnsIn | null | 'bad' {
  const was = draftOf(dns)
  const cachesize = whole(d.cachesize)
  if (isBad(cachesize)) return 'bad'
  const switches = Object.fromEntries(Object.entries(d.switches).filter(([n, on]) => was.switches[n] !== on))
  const others = Object.fromEntries(
    d.others.flatMap((o): Array<[string, string | null]> => {
      if (o.isNew) return o.name.trim() ? [[o.name.trim(), o.value]] : []
      if (o.removed) return [[o.name, null]]
      return o.value !== dns.values?.[o.name] ? [[o.name, o.value]] : []
    }),
  )
  const req: DnsIn = {
    ...(!sameList(words(d.forwarders), words(was.forwarders)) ? { forwarders: words(d.forwarders) } : {}),
    ...(d.domain.trim() !== was.domain ? { domain: d.domain.trim() } : {}),
    ...(!sameList(words(d.rebind), words(was.rebind)) ? { rebind_domains: words(d.rebind) } : {}),
    ...(!sameList(overrideList(d.overrides), overrideList(was.overrides)) ? { overrides: d.overrides.filter((o) => o.host.trim() || o.ip.trim()) } : {}),
    ...(Object.keys(switches).length ? { switches } : {}),
    ...(d.cachesize !== was.cachesize && cachesize !== null ? { cachesize } : {}),
    ...(Object.keys(others).length ? { others } : {}),
  }
  return Object.keys(req).length ? req : null
}

type FormProps = { routerId: string; short: string; dns: DnsConf; onApplied: () => void }

function DnsForm({ routerId, short, dns, onApplied }: FormProps) {
  const [draft, setDraft] = useState(() => draftOf(dns))
  const set = (patch: Partial<Draft>): void => setDraft({ ...draft, ...patch })
  const req = dnsRequest(dns, draft)
  const change = usePlanApply(`/api/routers/${routerId}/network/dns`, req === 'bad' ? null : req, onApplied)
  const toggle = ([name, text]: readonly [string, string]) => (
    <Toggle key={name} label={text} checked={draft.switches[name]} onChange={(on) => set({ switches: { ...draft.switches, [name]: on } })}>
      {text} <span className="muted mono">{name}</span>
    </Toggle>
  )
  const setOverride = (i: number, patch: Partial<Override>): void =>
    set({ overrides: draft.overrides.map((o, n) => (n === i ? { ...o, ...patch } : o)) })
  const setOther = (i: number, patch: Partial<Other>): void => set({ others: draft.others.map((o, n) => (n === i ? { ...o, ...patch } : o)) })
  return (
    <>
      <div className="grid">
        <label className="field">
          <span>Forwarders</span>
          <input className="in mono" aria-label="Forwarders" placeholder="the upstream from DHCP" value={draft.forwarders} onChange={(e) => set({ forwarders: e.target.value })} />
        </label>
        <label className="field">
          <span>Local domain</span>
          <input className="in mono" aria-label="Local domain" placeholder="none" value={draft.domain} onChange={(e) => set({ domain: e.target.value })} />
        </label>
        <label className="field">
          <span>Cache size</span>
          <input className="in mono" aria-label="Cache size" inputMode="numeric" placeholder="default" value={draft.cachesize} onChange={(e) => set({ cachesize: e.target.value })} />
        </label>
      </div>
      <div className="stack" style={{ gap: 6 }}>
        <div className="eyebrow">Rebind protection</div>
        {REBIND.map(toggle)}
        <label className="field">
          <span>Domains allowed private answers</span>
          <input className="in mono" aria-label="Rebind domains" placeholder="none" value={draft.rebind} onChange={(e) => set({ rebind: e.target.value })} />
        </label>
      </div>
      <div className="stack" style={{ gap: 6 }}>
        <div className="eyebrow">Overrides</div>
        {draft.overrides.map((o, i) => (
          <div className="row" key={i}>
            <input className="in mono" aria-label={`Host of override ${i + 1}`} placeholder="printer.lan" value={o.host} onChange={(e) => setOverride(i, { host: e.target.value })} />
            <span aria-hidden="true">→</span>
            <input className="in mono" aria-label={`IP of override ${i + 1}`} placeholder="192.168.1.20" value={o.ip} onChange={(e) => setOverride(i, { ip: e.target.value })} />
            <button className="btn" type="button" aria-label={`Remove override ${i + 1}`} onClick={() => set({ overrides: draft.overrides.filter((_, n) => n !== i) })}>
              Remove
            </button>
          </div>
        ))}
        <div className="row">
          <button className="btn" type="button" onClick={() => set({ overrides: [...draft.overrides, { host: '', ip: '' }] })}>
            + Override
          </button>
        </div>
      </div>
      <div className="stack" style={{ gap: 6 }}>
        <div className="eyebrow">Switches</div>
        {SWITCHES.map(toggle)}
      </div>
      <div className="stack" style={{ gap: 6 }}>
        <div className="eyebrow">Other dnsmasq options</div>
        {draft.others.map((o, i) => (
          <div className="row" key={i}>
            <input className="in mono" aria-label={`Name of dnsmasq option ${i + 1}`} value={o.name} readOnly={!o.isNew} onChange={(e) => setOther(i, { name: e.target.value })} />
            <input className="in mono" aria-label={`Value of dnsmasq option ${i + 1}`} value={o.value} disabled={o.removed} onChange={(e) => setOther(i, { value: e.target.value })} />
            <button
              className="btn"
              type="button"
              aria-label={`Remove dnsmasq option ${i + 1}`}
              aria-pressed={o.removed}
              onClick={() => (o.isNew ? set({ others: draft.others.filter((_, n) => n !== i) }) : setOther(i, { removed: !o.removed }))}
            >
              {o.removed ? 'Keep' : 'Remove'}
            </button>
          </div>
        ))}
        <div className="row">
          <button className="btn" type="button" onClick={() => set({ others: [...draft.others, { name: '', value: '', removed: false, isNew: true }] })}>
            + Option
          </button>
        </div>
      </div>
      {req === 'bad' && <div className="note x">Cache size is a whole number.</div>}
      <NetChange change={change} short={short} helpTopic={HELP.netDns} show={req !== null && req !== 'bad'} />
    </>
  )
}

type Props = { routerId: string; routerName: string; state: NetworkState; onApplied: () => void }

/** DNS (the LuCI DNS page): dnsmasq's forwarders, local domain, rebind protection, overrides and switches. */
export function DnsCard({ routerId, routerName, state, onApplied }: Props) {
  return (
    <section className="card stack" aria-labelledby="dns-h">
      <div className="hrow">
        <h2 id="dns-h">DNS</h2>
        <Help topic={HELP.netDns} />
      </div>
      {state.dns ? (
        <DnsForm routerId={routerId} short={shortName(routerName, routerId)} dns={state.dns} onApplied={onApplied} />
      ) : (
        <div className="muted">This router has no dnsmasq section.</div>
      )}
    </section>
  )
}
