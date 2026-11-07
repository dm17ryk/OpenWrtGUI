import { type ReactNode, useState } from 'react'
import type { FirewallState, RuleView } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help, HelpTip } from '../../help/Help'
import { NetChange } from '../net/NetChange'
import { OtherOptions } from './OtherOptions'
import { ruleAction, ruleMatch, ruleWhere } from './rules'
import { type Conf, type Draft, draftOf, emptyText, type Field, isPin, type Kind, KINDS, requestOf, sameRequest, sectionsOf } from './sections'

type Props = { kind: Kind; routerId: string; short: string; state: FirewallState; onApplied: () => void }
type Open = { was: Conf | null; draft: Draft; form: boolean; remove: boolean }

const EFFECT: Record<RuleView['effect'], string> = {
  allows: 'allows',
  blocks: 'blocks',
  'no-effect-allow': 'no effect · zone already allows this',
  'no-effect-block': 'no effect · zone already blocks this',
  other: 'other',
}

const PIN_NOTE = 'kept open by the app · change it on Zones and model'

/** The row's cells after its name, one per HEADS column. */
function Cells({ kind, c, state }: { kind: Kind; c: Conf; state: FirewallState }): ReactNode {
  const packets = state.counters[c.name ?? ''] ?? '—'
  if (kind === 'rule') {
    const view = state.rules.find((r) => r.conf.section === c.section)
    const rule = c as FirewallState['conf']['rules'][number]
    const action = ruleAction(rule.target)
    const dead = view?.effect.startsWith('no-effect')
    return (
      <>
        <td className="mono nowrap">{view ? ruleWhere(view) : `${rule.src ?? '—'} → ${rule.dest ?? 'this router'}`}</td>
        <td className="mono">{ruleMatch(rule)}</td>
        <td>
          <span className={`pol ${action.cls}`}>{action.label}</span>
        </td>
        <td className="mono">{view?.packets ?? '—'}</td>
        <td>{view && <span className={`b ${dead ? 'park' : 'neu'}`}>{EFFECT[view.effect]}</span>}</td>
      </>
    )
  }
  if (kind === 'redirect') {
    const r = c as FirewallState['conf']['redirects'][number]
    return (
      <>
        <td className="mono">{r.proto ?? 'tcp udp'}</td>
        <td className="mono">
          {r.src ?? '—'} :{r.src_dport ?? '—'}
        </td>
        <td className="mono">
          {r.dest_ip ?? '—'}
          {r.dest_port ? `:${r.dest_port}` : ''}
        </td>
        <td className="mono">{packets}</td>
      </>
    )
  }
  if (kind === 'nat') {
    const n = c as FirewallState['conf']['nats'][number]
    return (
      <>
        <td className="mono">{[n.src, n.src_ip].filter(Boolean).join(' · ') || '—'}</td>
        <td className="mono">{[n.dest_ip, n.dest_port].filter(Boolean).join(':') || 'any'}</td>
        <td>
          <span className={`pol ${n.target === 'ACCEPT' ? 'acc' : 'neu'}`}>{n.target.toLowerCase()}</span>
        </td>
        <td className="mono">{[n.snat_ip, n.snat_port].filter(Boolean).join(':') || '—'}</td>
        <td className="mono">{packets}</td>
      </>
    )
  }
  const s = c as FirewallState['conf']['ipsets'][number]
  return (
    <>
      <td className="mono">{s.family}</td>
      <td className="mono">{s.match.join(', ')}</td>
      <td className="mono">{s.entries.length}</td>
    </>
  )
}

const HEADS: Record<Kind, string[]> = {
  rule: ['Where', 'Match', 'Action', 'Packets', 'Effect'],
  redirect: ['Protocol', 'From', 'To device', 'Packets'],
  nat: ['Source', 'Destination', 'Action', 'Rewrite to', 'Packets'],
  ipset: ['Family', 'Match', 'Entries'],
}

function FieldInput({ field, value, zones, onChange }: { field: Field; value: string; zones: string[]; onChange: (v: string) => void }) {
  if (field.type === 'zone' || field.type === 'select') {
    const options = field.type === 'select' ? (field.options ?? []) : zones
    return (
      <select className="in" aria-label={field.label} value={value} onChange={(e) => onChange(e.target.value)}>
        {field.type === 'zone' && field.optional && <option value="">— (this router)</option>}
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
        {field.type === 'zone' && field.optional && <option value="*">any zone</option>}
      </select>
    )
  }
  if (field.type === 'lines') return <textarea className="in mono" aria-label={field.label} rows={4} value={value} onChange={(e) => onChange(e.target.value)} />
  return <input className="in mono" aria-label={field.label} value={value} onChange={(e) => onChange(e.target.value)} />
}

/** Traffic rules, port forwards, NAT rules or IP sets (LuCI's Network › Firewall tabs): the list and one editor. */
export function SectionTab({ kind, routerId, short, state, onApplied }: Props) {
  const spec = KINDS[kind]
  const [open, setOpen] = useState<Open | null>(null)
  const rows = sectionsOf(kind, state.conf)
  const body = (() => {
    if (!open) return null
    if (open.remove && open.was) return { upserts: [], deletes: [open.was.section] }
    if (!(open.draft.values.name ?? '').trim()) return null
    if (open.was && sameRequest(kind, open.was, open.draft)) return null
    return { upserts: [requestOf(kind, open.was, open.draft)], deletes: [] }
  })()
  const change = usePlanApply(`/api/routers/${routerId}/firewall/${spec.path}`, body, () => {
    setOpen(null)
    onApplied()
  })
  const draft = open?.draft
  const setDraft = (patch: Partial<Draft>): void => setOpen(open && { ...open, draft: { ...open.draft, ...patch } })
  const zones = state.conf.zones.map((z) => z.name)
  const name = (c: Conf): string => c.name ?? c.section
  const editor = open?.form && draft && (
    <fieldset className="stack editor" aria-label={open.was ? `${spec.one[0].toUpperCase()}${spec.one.slice(1)} ${name(open.was)}` : `New ${spec.one}`}>
      <legend>{open.was ? name(open.was) : `New ${spec.one}`}</legend>
      <div className="grid">
        {spec.fields.map((f) => (
          <label key={f.key} className="field">
            <span>{f.label}</span>
            <FieldInput field={f} value={draft.values[f.key] ?? ''} zones={zones} onChange={(v) => setDraft({ values: { ...draft.values, [f.key]: v } })} />
          </label>
        ))}
      </div>
      <label className="check">
        <input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ enabled: e.target.checked })} />
        Enabled
      </label>
      <OtherOptions rows={draft.others} onChange={(others) => setDraft({ others })} />
      <div className="row">
        {open.was && (
          <button className="btn danger" type="button" aria-pressed={open.remove} onClick={() => setOpen({ ...open, remove: !open.remove })}>
            {open.remove ? `Keep this ${spec.one}` : `Delete ${spec.one}`}
          </button>
        )}
        <button className="btn" type="button" onClick={() => setOpen(null)}>
          Cancel
        </button>
      </div>
    </fieldset>
  )
  return (
    <section className="card stack" aria-labelledby={`fw-${kind}-h`}>
      <div className="hrow">
        <h2 id={`fw-${kind}-h`}>{spec.title}</h2>
        <Help topic={spec.help} />
        {kind === 'rule' && <span className="muted">from /etc/config/firewall, live packet counters, in the order fw4 applies them</span>}
        <span className="spacer" />
        <HelpTip topic={spec.help}>
          <button className="btn" type="button" onClick={() => setOpen({ was: null, draft: draftOf(kind, null), form: true, remove: false })}>
            {spec.add}
          </button>
        </HelpTip>
      </div>
      {rows.length === 0 ? (
        <div className="note">{emptyText(kind, short, state.conf)}</div>
      ) : (
        <div className="scroll-x">
          <table className="tbl" aria-label={spec.title}>
            <thead>
              <tr>
                <th>Name</th>
                {HEADS[kind].map((h) => (
                  <th key={h}>{h}</th>
                ))}
                <th>On</th>
                <th>
                  <span className="sr-only">Edit</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => {
                const editing = open?.was?.section === c.section ? open : null
                const on = editing ? editing.draft.enabled : c.enabled
                const dead = kind === 'rule' && state.rules.find((r) => r.conf.section === c.section)?.effect.startsWith('no-effect')
                return (
                  <tr key={c.section} className={dead ? 'flag' : undefined}>
                    <td>{name(c)}</td>
                    <Cells kind={kind} c={c} state={state} />
                    {kind === 'rule' && isPin(c) ? (
                      <td colSpan={2} className="muted small">
                        {PIN_NOTE}
                      </td>
                    ) : (
                      <>
                        <td>
                          <input
                            type="checkbox"
                            aria-label={`${name(c)} on`}
                            checked={on}
                            onChange={(e) => {
                              const base = editing ?? { was: c, draft: draftOf(kind, c), form: false, remove: false }
                              setOpen({ ...base, draft: { ...base.draft, enabled: e.target.checked } })
                            }}
                          />
                        </td>
                        <td>
                          <button className="btn" type="button" onClick={() => setOpen({ was: c, draft: editing?.draft ?? draftOf(kind, c), form: true, remove: false })}>
                            Edit
                          </button>
                        </td>
                      </>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {editor}
      <NetChange change={change} short={short} helpTopic={spec.help} show={body !== null} />
    </section>
  )
}
