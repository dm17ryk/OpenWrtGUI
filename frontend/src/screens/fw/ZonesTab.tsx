import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { apiFetch } from '../../api/client'
import type { FirewallState, NetworkState, Policy, ZoneConf, ZoneIn, ZonesIn } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

const POLICIES: readonly Policy[] = ['ACCEPT', 'REJECT', 'DROP']
const POLICY_FIELDS = [
  ['input', 'Input'],
  ['forward', 'Forward'],
  ['output', 'Output'],
] as const

type Draft = { zone: ZoneIn; forwardsTo: string[]; others: Array<[string, string]>; remove: boolean }
type Props = { routerId: string; short: string; state: FirewallState; onApplied: () => void }

const forwardsOf = (state: FirewallState, name: string): string[] =>
  state.conf.forwardings.filter((f) => f.enabled && f.src === name && f.dest).map((f) => f.dest as string)

function draftOf(state: FirewallState, z: ZoneConf | null): Draft {
  if (z === null) {
    return { zone: { section: null, name: '', networks: [], input: 'REJECT', output: 'ACCEPT', forward: 'REJECT', masq: false, mtu_fix: false }, forwardsTo: [], others: [], remove: false }
  }
  const zone: ZoneIn = { section: z.section, name: z.name, networks: [...z.networks], input: z.input, output: z.output, forward: z.forward, masq: z.masq, mtu_fix: z.mtu_fix }
  return { zone, forwardsTo: forwardsOf(state, z.name), others: Object.entries(z.others ?? {}), remove: false }
}

/** The zones request: the zone as edited, its other options changed or removed, and forwardings when they changed. */
function zonesRequest(state: FirewallState, was: ZoneConf | null, d: Draft): ZonesIn | null {
  if (d.remove && was) return { upserts: [], deletes: [was.section] }
  if (!d.zone.name) return null
  const before = was?.others ?? {}
  const others: Record<string, string | null> = {}
  for (const [k, v] of d.others) if (k && before[k] !== v) others[k] = v
  for (const k of Object.keys(before)) if (!d.others.some(([n]) => n === k)) others[k] = null
  const fwdBefore = was ? forwardsOf(state, was.name) : []
  const fwdChanged = [...fwdBefore].sort().join() !== [...d.forwardsTo].sort().join() || (was !== null && was.name !== d.zone.name && fwdBefore.length > 0)
  const forwardings = fwdChanged
    ? [
        ...state.conf.forwardings.filter((f) => f.enabled && f.src && f.dest && f.src !== was?.name).map((f) => ({ src: f.src as string, dest: f.dest as string })),
        ...d.forwardsTo.map((dest) => ({ src: d.zone.name, dest })),
      ]
    : null
  const same =
    was !== null &&
    Object.keys(others).length === 0 &&
    !fwdChanged &&
    d.zone.name === was.name &&
    d.zone.networks?.join() === was.networks.join() &&
    d.zone.input === was.input &&
    d.zone.output === was.output &&
    d.zone.forward === was.forward &&
    d.zone.masq === was.masq &&
    d.zone.mtu_fix === was.mtu_fix
  if (same) return null
  return { upserts: [{ ...d.zone, others }], deletes: [], forwardings }
}

function Pol({ p }: { p: Policy }) {
  return <span className={`pol ${p === 'ACCEPT' ? 'acc' : 'rej'}`}>{p.toLowerCase()}</span>
}

/** Zones (spec 7.6): networks, policies, masquerade, MSS clamp and forwardings, with an editor per zone. */
export function ZonesTab({ routerId, short, state, onApplied }: Props) {
  const [open, setOpen] = useState<{ was: ZoneConf | null; draft: Draft } | null>(null)
  const net = useQuery({ queryKey: ['network', routerId], queryFn: () => apiFetch<NetworkState>(`/api/routers/${routerId}/network`), enabled: open !== null })
  const body = open ? zonesRequest(state, open.was, open.draft) : null
  const change = usePlanApply(`/api/routers/${routerId}/firewall/zones`, body, () => {
    setOpen(null)
    onApplied()
  })
  const edit = (patch: Partial<Draft>): void => setOpen(open && { ...open, draft: { ...open.draft, ...patch } })
  const setZone = (patch: Partial<ZoneIn>): void => {
    if (open) edit({ zone: { ...open.draft.zone, ...patch } })
  }
  const draft = open?.draft
  const interfaces = (net.data?.interfaces ?? []).flatMap((i) => (i.conf && i.conf.name !== 'loopback' ? [i.conf.name] : []))
  const networks = [...new Set([...interfaces, ...(open?.was?.networks ?? [])])]
  return (
    <section className="card stack" aria-labelledby="fw-zones-h">
      <div className="hrow">
        <h2 id="fw-zones-h">Zones</h2>
        <Help topic={HELP.fwZones} />
        <span className="spacer" />
        <HelpTip topic={HELP.fwZones}>
          <button className="btn" type="button" onClick={() => setOpen({ was: null, draft: draftOf(state, null) })}>
            + Zone
          </button>
        </HelpTip>
      </div>
      <div className="scroll-x">
        <table className="tbl" aria-label="Zones">
          <thead>
            <tr>
              <th>Zone</th>
              <th>Networks</th>
              <th>Input</th>
              <th>Forward</th>
              <th>Output</th>
              <th>Masquerade</th>
              <th>MSS clamp</th>
              <th>Forwards to</th>
              <th>
                <span className="sr-only">Edit</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {state.conf.zones.map((z) => (
              <tr key={z.section}>
                <td>
                  <strong>{z.name}</strong>
                </td>
                <td className="mono">{z.networks.join(', ') || '—'}</td>
                <td>
                  <Pol p={z.input} />
                </td>
                <td>
                  <Pol p={z.forward} />
                </td>
                <td>
                  <Pol p={z.output} />
                </td>
                <td>{z.masq ? 'yes' : '—'}</td>
                <td>{z.mtu_fix ? 'yes' : '—'}</td>
                <td className="mono">{forwardsOf(state, z.name).join(', ') || '—'}</td>
                <td>
                  <button className="btn" type="button" onClick={() => setOpen({ was: z, draft: draftOf(state, z) })}>
                    Edit
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {open && draft && (
        <fieldset className="stack editor" aria-label={open.was ? `Zone ${open.was.name}` : 'New zone'}>
          <legend>{open.was ? `Zone ${open.was.name}` : 'New zone'}</legend>
          <div className="grid">
            <label className="field">
              <span>Name</span>
              <input className="in" value={draft.zone.name} onChange={(e) => setZone({ name: e.target.value })} />
            </label>
            {POLICY_FIELDS.map(([key, label]) => (
              <label key={key} className="field">
                <span>{label}</span>
                <select className="in" value={draft.zone[key]} onChange={(e) => setZone({ [key]: e.target.value as Policy })}>
                  {POLICIES.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
          <div className="row" role="group" aria-label="Networks">
            <span className="muted">Networks</span>
            {networks.map((n) => (
              <label key={n} className="check">
                <input
                  type="checkbox"
                  checked={draft.zone.networks?.includes(n) ?? false}
                  onChange={(e) => setZone({ networks: e.target.checked ? [...(draft.zone.networks ?? []), n] : (draft.zone.networks ?? []).filter((x) => x !== n) })}
                />
                {n}
              </label>
            ))}
          </div>
          <div className="row">
            <label className="check">
              <input type="checkbox" checked={draft.zone.masq ?? false} onChange={(e) => setZone({ masq: e.target.checked })} />
              Masquerade
            </label>
            <label className="check">
              <input type="checkbox" checked={draft.zone.mtu_fix ?? false} onChange={(e) => setZone({ mtu_fix: e.target.checked })} />
              MSS clamp
            </label>
          </div>
          <div className="row" role="group" aria-label="Forwards to">
            <span className="muted">Forwards to</span>
            {state.conf.zones
              .filter((z) => z.section !== open.was?.section)
              .map((z) => (
                <label key={z.section} className="check">
                  <input
                    type="checkbox"
                    checked={draft.forwardsTo.includes(z.name)}
                    onChange={(e) => edit({ forwardsTo: e.target.checked ? [...draft.forwardsTo, z.name] : draft.forwardsTo.filter((x) => x !== z.name) })}
                  />
                  {z.name}
                </label>
              ))}
          </div>
          <div className="stack" style={{ gap: 6 }}>
            <span className="muted">Other options</span>
            {draft.others.map(([k, v], i) => (
              <div key={i} className="row">
                <input className="in mono" aria-label={`Option ${i + 1} name`} value={k} onChange={(e) => edit({ others: draft.others.map((o, j) => (j === i ? [e.target.value, o[1]] : o)) })} />
                <input className="in mono" aria-label={`Option ${i + 1} value`} value={v} onChange={(e) => edit({ others: draft.others.map((o, j) => (j === i ? [o[0], e.target.value] : o)) })} />
                <button className="btn" type="button" onClick={() => edit({ others: draft.others.filter((_, j) => j !== i) })}>
                  Remove
                </button>
              </div>
            ))}
            <div className="row">
              <button className="btn" type="button" onClick={() => edit({ others: [...draft.others, ['', '']] })}>
                + Option
              </button>
              {open.was && (
                <button className="btn danger" type="button" onClick={() => edit({ remove: !draft.remove })} aria-pressed={draft.remove}>
                  {draft.remove ? 'Keep this zone' : 'Delete zone'}
                </button>
              )}
              <button className="btn" type="button" onClick={() => setOpen(null)}>
                Cancel
              </button>
            </div>
          </div>
          <NetChange change={change} short={short} helpTopic={HELP.fwZones} show={body !== null} />
        </fieldset>
      )}
    </section>
  )
}
