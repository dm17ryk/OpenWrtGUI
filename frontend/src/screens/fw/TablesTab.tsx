import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { apiFetch } from '../../api/client'
import type { FirewallState, GuardOut, NftObject, TableIn } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import { guardReasonText } from '../../shell/guardText'
import { NetChange } from '../net/NetChange'
import { chainsOf, type NftChain, parseRuleset, ruleBody } from './nfttext'

type Keep = 'runtime' | 'include'
type Row = { chain: string; text: string; packets: number | null; editing: boolean }
type Edit = { key: string; rows: Row[] | null; chains: Array<{ name: string; declaration: string }>; remove: boolean; keep: Keep }
type Add = { family: string; name: string; keep: Keep }
type Props = {
  routerId: string
  short: string
  state: FirewallState
  unlocked: readonly string[]
  onUnlock: (key: string) => void
  onLock: (key: string) => void
  onZones: () => void
  onApplied: () => void
}

const FAMILIES = ['inet', 'ip', 'ip6', 'bridge', 'netdev', 'arp'] as const

function ownerBadge(o: NftObject): { cls: string; text: string } {
  if (o.owner === 'fw4') return { cls: 'b neu', text: 'fw4' }
  if (o.owner === 'app') return { cls: 'b own', text: 'this app' }
  if (o.owner === 'known') return { cls: 'b har', text: `harness · ${o.writer ?? 'unknown'}` }
  return { cls: 'b park', text: 'unknown' }
}

function what(o: NftObject): string {
  if (o.owner === 'fw4') return 'Zones and rules from /etc/config/firewall'
  if (o.owner === 'app') return 'Fault scenarios armed from the Faults screen'
  return o.depends ?? ''
}

const rowsOf = (chains: NftChain[]): Row[] => chains.flatMap((c) => c.rules.map((r) => ({ chain: c.name, text: r.text, packets: r.packets, editing: false })))
const bodies = (rows: Row[]): Array<{ chain: string; body: string }> => rows.filter((r) => r.text.trim()).map((r) => ({ chain: r.chain, body: ruleBody(r.text) }))

function keepHint(o: NftObject, keep: Keep): string {
  if (keep === 'include') return `survives reboot; fw4 loads it at ${o.chain ? 'table-post' : 'ruleset-post'}`
  return o.chain ? 'gone at the next fw4 reload or reboot' : 'gone at the next reboot'
}

function KeepSeg({ keep, onChange }: { keep: Keep; onChange: (k: Keep) => void }) {
  return (
    <div className="seg" role="group" aria-label="Keep the change">
      <button type="button" className={keep === 'runtime' ? 'on' : ''} aria-pressed={keep === 'runtime'} onClick={() => onChange('runtime')}>
        Runtime only
      </button>
      <button type="button" className={keep === 'include' ? 'on' : ''} aria-pressed={keep === 'include'} onClick={() => onChange('include')}>
        Saved as fw4 include
      </button>
    </div>
  )
}

/**
 * Every nftables table and tc hook with its owner (spec 7.6, D12). Tables someone else owns are locked: Unlock says
 * who relies on them first, and each change then carries the override, which the backend audits.
 */
export function TablesTab({ routerId, short, state, unlocked, onUnlock, onLock, onZones, onApplied }: Props) {
  const guard = useQuery({ queryKey: ['guard'], queryFn: () => apiFetch<GuardOut>('/api/guard') })
  const ruleset = useQuery({ queryKey: ['firewall-ruleset', routerId], queryFn: () => apiFetch<{ text: string }>(`/api/routers/${routerId}/firewall/ruleset`) })
  const [asking, setAsking] = useState<string | null>(null)
  const [edit, setEdit] = useState<Edit | null>(null)
  const [add, setAdd] = useState<Add | null>(null)
  const live = guard.data?.live ?? false
  const parsed = parseRuleset(ruleset.data?.text ?? '')
  const obj = edit ? state.objects.find((o) => o.key === edit.key) : undefined
  const open = obj && (obj.owner === 'app' || unlocked.includes(obj.key)) ? obj : undefined
  const current = open ? chainsOf(parsed, open) : []
  const rows = edit?.rows ?? rowsOf(current)
  const editBody = ((): TableIn | null => {
    if (!open || !edit) return null
    const override = open.owner !== 'app'
    if (edit.remove) return { key: open.key, action: 'delete', override, keep: edit.keep }
    const rules = bodies(rows)
    const same = JSON.stringify(rules) === JSON.stringify(bodies(rowsOf(current)))
    if (same && edit.chains.length === 0 && edit.keep === 'runtime') return null
    const chains = edit.chains.filter((c) => c.name.trim())
    return {
      key: open.key,
      action: 'edit',
      override,
      keep: edit.keep,
      rules,
      ...(chains.length ? { chains: [...current.map((c) => ({ name: c.name, declaration: c.declaration })), ...chains.map((c) => ({ name: c.name.trim(), declaration: c.declaration.trim() || null }))] } : {}),
    }
  })()
  const addBody: TableIn | null = add && add.name.trim() ? { action: 'add', family: add.family, name: add.name.trim(), keep: add.keep } : null
  const changeEdit = usePlanApply(`/api/routers/${routerId}/firewall/tables`, editBody, () => {
    setEdit(null)
    onApplied()
  })
  const changeAdd = usePlanApply(`/api/routers/${routerId}/firewall/tables`, addBody, () => {
    setAdd(null)
    onApplied()
  })
  const setRows = (next: Row[]): void => setEdit(edit && { ...edit, rows: next })
  const chainNames = [...current.map((c) => c.name), ...(edit?.chains.map((c) => c.name).filter(Boolean) ?? [])]
  const asked = state.objects.find((o) => o.key === asking)
  const openEditor = (key: string): void => setEdit({ key, rows: null, chains: [], remove: false, keep: 'runtime' })
  const lock = (key: string): void => {
    onLock(key)
    if (edit?.key === key) setEdit(null)
  }
  return (
    <section className="card stack" aria-labelledby="fw-tables-h">
      <div className="hrow">
        <h2 id="fw-tables-h">All nftables tables on {short}</h2>
        <Help topic={HELP.fwTables} />
        <span className="muted">every table and hook has an owner. Tables owned by someone else are locked until you unlock them.</span>
        <span className="spacer" />
        <HelpTip topic={HELP.fwTables}>
          <button className="btn" type="button" disabled={live} onClick={() => setAdd(add ? null : { family: 'inet', name: '', keep: 'runtime' })}>
            + Add table
          </button>
        </HelpTip>
      </div>
      <div className="scroll-x">
        <table className="tbl" aria-label="nftables tables">
          <thead>
            <tr>
              <th>Table</th>
              <th>Owner</th>
              <th>What it does</th>
              <th>Rules</th>
              <th>
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {state.objects.map((o) => {
              const badge = ownerBadge(o)
              const isOpen = unlocked.includes(o.key)
              return (
                <tr key={o.key}>
                  <td className="mono nowrap">{o.key}</td>
                  <td>
                    <span className={badge.cls}>{badge.text}</span>
                  </td>
                  <td>{what(o)}</td>
                  <td className="mono">{o.rules}</td>
                  <td className="nowrap">
                    {o.owner === 'fw4' && (
                      <button className="btn" type="button" onClick={onZones}>
                        Zones and rules
                      </button>
                    )}
                    {o.owner === 'app' && (
                      <>
                        <Link className="btn" to={`/routers/${routerId}/faults`}>
                          Open faults
                        </Link>{' '}
                        <button className="btn" type="button" disabled={live} onClick={() => openEditor(o.key)}>
                          Edit
                        </button>
                      </>
                    )}
                    {(o.owner === 'known' || o.owner === 'unknown') &&
                      (isOpen ? (
                        <>
                          <span className="b park">unlocked</span>{' '}
                          <button className="btn" type="button" onClick={() => lock(o.key)}>
                            Lock
                          </button>
                        </>
                      ) : (
                        <HelpTip topic={HELP.fwTables}>
                          <button className="btn" type="button" disabled={live} onClick={() => setAsking(o.key)}>
                            {live ? 'Locked during run' : 'Unlock…'}
                          </button>
                        </HelpTip>
                      ))}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {state.tc.length > 0 && (
        <div className="scroll-x">
          <table className="tbl" aria-label="Traffic-control hooks">
            <thead>
              <tr>
                <th>Device</th>
                <th>Kind</th>
                <th>Handle</th>
                <th>Owner</th>
              </tr>
            </thead>
            <tbody>
              {state.tc.map((h) => (
                <tr key={`${h.dev} ${h.handle}`}>
                  <td className="mono">{h.dev}</td>
                  <td className="mono">{h.kind}</td>
                  <td className="mono">{h.handle}</td>
                  <td>
                    <span className={h.owner === 'app' ? 'b own' : 'b park'}>{h.owner === 'app' ? 'this app' : 'unknown · read-only'}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {asked && !unlocked.includes(asked.key) && (
        <div className="note h stack" role="group" aria-label={`Unlock ${asked.key}?`}>
          <strong>
            Unlock <span className="mono">{asked.key}</span>?
          </strong>
          <dl className="facts">
            <dt>Owner</dt>
            <dd>{asked.writer ?? 'unknown'}</dd>
            <dt>What depends on it</dt>
            <dd>{asked.depends ?? '—'}</dd>
            <dt>Running now</dt>
            <dd>{guard.data?.live ? guardReasonText(guard.data) : 'no harness run (Bench Guard clear)'}</dd>
          </dl>
          <span>The override is written to the audit log. The table locks again when you close this router, or with Lock.</span>
          <div className="row">
            <button
              className="btn pri"
              type="button"
              disabled={live}
              onClick={() => {
                onUnlock(asked.key)
                setAsking(null)
                openEditor(asked.key)
              }}
            >
              Unlock
            </button>
            <button className="btn" type="button" onClick={() => setAsking(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {open && edit && (
        <fieldset className="stack editor" aria-label={`Table ${open.key}`}>
          <legend className="mono">{open.key}</legend>
          <div className="row">
            <span className="b park">{open.owner === 'app' ? 'this app' : 'unlocked · edits allowed'}</span>
            <span className="spacer" />
            <button className="btn" type="button" disabled={chainNames.length === 0} onClick={() => setRows([...rows, { chain: chainNames[0], text: '', packets: null, editing: true }])}>
              + Rule
            </button>
            {!open.chain && (
              <>
                <button className="btn" type="button" onClick={() => setEdit({ ...edit, chains: [...edit.chains, { name: '', declaration: '' }] })}>
                  + Chain
                </button>
                <button className="btn danger" type="button" aria-pressed={edit.remove} onClick={() => setEdit({ ...edit, remove: !edit.remove })}>
                  {edit.remove ? 'Keep the table' : 'Delete table'}
                </button>
              </>
            )}
          </div>
          {edit.chains.map((c, i) => (
            <div key={i} className="row">
              <input className="in mono" aria-label={`New chain ${i + 1} name`} value={c.name} onChange={(e) => setEdit({ ...edit, chains: edit.chains.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} />
              <input
                className="in mono"
                aria-label={`New chain ${i + 1} declaration`}
                placeholder="type filter hook prerouting priority 0; policy accept;"
                value={c.declaration}
                onChange={(e) => setEdit({ ...edit, chains: edit.chains.map((x, j) => (j === i ? { ...x, declaration: e.target.value } : x)) })}
              />
            </div>
          ))}
          <div className="scroll-x">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Chain</th>
                  <th>Rule</th>
                  <th>Packets</th>
                  <th>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const n = rows.slice(0, i + 1).filter((x) => x.chain === r.chain).length
                  const update = (patch: Partial<Row>): void => setRows(rows.map((x, j) => (j === i ? { ...x, ...patch } : x)))
                  return (
                    <tr key={i}>
                      <td className="mono">
                        {r.editing && r.packets === null && chainNames.length > 1 ? (
                          <select className="in" aria-label={`Chain of rule ${i + 1}`} value={r.chain} onChange={(e) => update({ chain: e.target.value })}>
                            {chainNames.map((c) => (
                              <option key={c}>{c}</option>
                            ))}
                          </select>
                        ) : (
                          r.chain
                        )}
                      </td>
                      <td className="mono">
                        {r.editing ? <input className="in mono" aria-label={`${r.chain} rule ${n}`} value={r.text} onChange={(e) => update({ text: e.target.value })} /> : r.text}
                      </td>
                      <td className="mono">{r.packets ?? '—'}</td>
                      <td className="nowrap">
                        {!r.editing && (
                          <button className="btn" type="button" onClick={() => update({ editing: true, text: ruleBody(r.text) })}>
                            Edit
                          </button>
                        )}{' '}
                        <button className="btn" type="button" onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                          Delete
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div className="row">
            <span>Keep the change</span>
            <KeepSeg keep={edit.keep} onChange={(keep) => setEdit({ ...edit, keep })} />
            <span className="muted small">{keepHint(open, edit.keep)}</span>
          </div>
          <NetChange change={changeEdit} short={short} helpTopic={HELP.fwTables} show={editBody !== null} />
        </fieldset>
      )}
      {add && (
        <fieldset className="stack editor" aria-label="New table">
          <legend>New table</legend>
          <div className="row">
            <div className="seg" role="group" aria-label="Table family">
              {FAMILIES.map((f) => (
                <button key={f} type="button" className={add.family === f ? 'on' : ''} aria-pressed={add.family === f} onClick={() => setAdd({ ...add, family: f })}>
                  {f}
                </button>
              ))}
            </div>
            <label className="field">
              <span>Name</span>
              <input className="in mono" value={add.name} onChange={(e) => setAdd({ ...add, name: e.target.value })} />
            </label>
            <span className="mono">owg_{add.name}</span>
          </div>
          <div className="row">
            <span>Keep the change</span>
            <KeepSeg keep={add.keep} onChange={(keep) => setAdd({ ...add, keep })} />
          </div>
          <NetChange change={changeAdd} short={short} helpTopic={HELP.fwTables} show={addBody !== null} />
        </fieldset>
      )}
    </section>
  )
}
