import { useState } from 'react'
import type { NetworkState, RouteConf, RouteIn, RuleConf, RuleIn } from '../../api/types'
import { Toggle } from '../../components/Toggle'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { LiveRoutes } from './LiveRoutes'
import { NetChange } from './NetChange'
import { isBad, noRows, type RowSet, shortName, toggled, upsertsOf, whole } from './rows'

type RouteRow = { section: string | null; kind: RouteIn['kind']; interface: string; target: string; gateway: string; metric: string; table: string; type: string | null; enabled: boolean }
type RuleRow = { section: string | null; kind: RuleIn['kind']; priority: string; src: string; dest: string; in_iface: string; out_iface: string; lookup: string; action: string | null; enabled: boolean }
type RouteText = 'target' | 'gateway' | 'metric' | 'table'
type RuleText = 'priority' | 'src' | 'dest' | 'lookup'

const routeOf = (r: RouteConf): RouteRow => ({
  section: r.section,
  kind: r.kind,
  interface: r.interface ?? '',
  target: r.target,
  gateway: r.gateway ?? '',
  metric: r.metric === null ? '' : String(r.metric),
  table: r.table ?? '',
  type: r.type,
  enabled: !r.disabled,
})

const ruleOf = (r: RuleConf): RuleRow => ({
  section: r.section,
  kind: r.kind,
  priority: r.priority === null ? '' : String(r.priority),
  src: r.src ?? '',
  dest: r.dest ?? '',
  in_iface: r.in_iface ?? '',
  out_iface: r.out_iface ?? '',
  lookup: r.lookup ?? '',
  action: r.action,
  enabled: !r.disabled,
})

const opt = <K extends string>(key: K, text: string) => (text.trim() ? { [key]: text.trim() } : {})

function routeIn(r: RouteRow): RouteIn | 'bad' {
  const metric = whole(r.metric)
  if (isBad(metric)) return 'bad'
  return {
    ...(r.section ? { section: r.section } : {}),
    kind: r.kind,
    interface: r.interface,
    target: r.target.trim(),
    ...opt('gateway', r.gateway),
    ...(metric !== null ? { metric } : {}),
    ...opt('table', r.table),
    ...(r.type ? { type: r.type } : {}),
    disabled: !r.enabled,
  }
}

function ruleIn(r: RuleRow): RuleIn | 'bad' {
  const priority = whole(r.priority)
  if (isBad(priority)) return 'bad'
  return {
    ...(r.section ? { section: r.section } : {}),
    kind: r.kind,
    ...(priority !== null ? { priority } : {}),
    ...opt('src', r.src),
    ...opt('dest', r.dest),
    ...opt('in_iface', r.in_iface),
    ...opt('out_iface', r.out_iface),
    ...opt('lookup', r.lookup),
    ...(r.action ? { action: r.action } : {}),
    disabled: !r.enabled,
  }
}

type Props = { routerId: string; routerName: string; state: NetworkState; onApplied: () => void }

/** Static routes and policy rules (network `route`/`route6`, `rule`/`rule6`), applied with a rollback. */
export function RoutesCard({ routerId, routerName, state, onApplied }: Props) {
  const [family, setFamily] = useState<4 | 6>(4)
  const [routes, setRoutes] = useState<RowSet<RouteRow>>(noRows)
  const [rules, setRules] = useState<RowSet<RuleRow>>(noRows)
  const names = state.interfaces.flatMap((v) => (v.conf ? [v.conf.name] : []))
  const routeKind = family === 4 ? 'route' : 'route6'
  const ruleKind = family === 4 ? 'rule' : 'rule6'
  const newRoute: RouteRow = { section: null, kind: routeKind, interface: state.own_interface ?? names[0] ?? '', target: '', gateway: '', metric: '', table: '', type: null, enabled: true }
  const newRule: RuleRow = { section: null, kind: ruleKind, priority: '', src: '', dest: '', in_iface: '', out_iface: '', lookup: '', action: null, enabled: true }

  const routeUps = upsertsOf(state.routes, routes, routeOf, (r) => r.target.trim() !== '').map(routeIn)
  const ruleUps = upsertsOf(state.rules, rules, ruleOf, (r) => [r.priority, r.src, r.dest, r.in_iface, r.out_iface, r.lookup].some((t) => t.trim())).map(ruleIn)
  const isBadRow = routeUps.includes('bad') || ruleUps.includes('bad')
  const isEmpty = !routeUps.length && !ruleUps.length && !routes.deleted.length && !rules.deleted.length
  const body =
    isBadRow || isEmpty
      ? null
      : {
          upserts: routeUps.filter((r): r is RouteIn => r !== 'bad'),
          deletes: routes.deleted,
          rule_upserts: ruleUps.filter((r): r is RuleIn => r !== 'bad'),
          rule_deletes: rules.deleted,
        }
  const change = usePlanApply(`/api/routers/${routerId}/network/routes`, body, () => {
    setRoutes(noRows())
    setRules(noRows())
    onApplied()
  })

  const ifaceSelect = (label: string, value: string, onChange: (v: string) => void, anyText?: string) => (
    <select className="in" aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      {anyText !== undefined && <option value="">{anyText}</option>}
      {names.map((n) => (
        <option key={n} value={n}>
          {n}
        </option>
      ))}
    </select>
  )
  const routeLine = (row: RouteRow, label: string, update: (r: RouteRow) => void, remove: { text: string; label: string; pressed?: boolean; onClick: () => void }) => {
    const text = (key: RouteText, name: string, placeholder: string) => (
      <td>
        <input className="in mono" aria-label={`${name} of ${label}`} placeholder={placeholder} value={row[key]} onChange={(e) => update({ ...row, [key]: e.target.value })} />
      </td>
    )
    return (
      <tr key={label}>
        <td>{ifaceSelect(`Interface of ${label}`, row.interface, (v) => update({ ...row, interface: v }))}</td>
        {text('target', 'Target', family === 4 ? '10.8.0.0/24' : 'fd00:8::/64')}
        {text('gateway', 'Gateway', 'none')}
        {text('metric', 'Metric', '0')}
        {text('table', 'Table', 'main')}
        <td>
          <Toggle label={`${label} on`} checked={row.enabled} onChange={(on) => update({ ...row, enabled: on })} />
        </td>
        <td>
          <button className="btn danger" type="button" aria-label={remove.label} aria-pressed={remove.pressed} onClick={remove.onClick}>
            {remove.text}
          </button>
        </td>
      </tr>
    )
  }
  const ruleLine = (row: RuleRow, label: string, update: (r: RuleRow) => void, remove: { text: string; label: string; pressed?: boolean; onClick: () => void }) => {
    const text = (key: RuleText, name: string, placeholder: string) => (
      <td>
        <input className="in mono" aria-label={`${name} of ${label}`} placeholder={placeholder} value={row[key]} onChange={(e) => update({ ...row, [key]: e.target.value })} />
      </td>
    )
    return (
      <tr key={label}>
        {text('priority', 'Priority', 'auto')}
        {text('src', 'From', 'all')}
        {text('dest', 'To', 'all')}
        <td>{ifaceSelect(`In of ${label}`, row.in_iface, (v) => update({ ...row, in_iface: v }), 'any')}</td>
        <td>{ifaceSelect(`Out of ${label}`, row.out_iface, (v) => update({ ...row, out_iface: v }), 'any')}</td>
        {text('lookup', 'Lookup', 'main')}
        <td>
          <Toggle label={`${label} on`} checked={row.enabled} onChange={(on) => update({ ...row, enabled: on })} />
        </td>
        <td>
          <button className="btn danger" type="button" aria-label={remove.label} aria-pressed={remove.pressed} onClick={remove.onClick}>
            {remove.text}
          </button>
        </td>
      </tr>
    )
  }

  return (
    <section className="card stack" aria-labelledby="routes-h">
      <div className="row">
        <div className="hrow">
          <h2 id="routes-h">Static routes and rules</h2>
          <Help topic={HELP.netRoutes} />
        </div>
        <div className="seg" role="group" aria-label="Address family">
          {([4, 6] as const).map((f) => (
            <button key={f} type="button" className={family === f ? 'on' : ''} aria-pressed={family === f} onClick={() => setFamily(f)}>
              IPv{f}
            </button>
          ))}
        </div>
        <div className="spacer" />
        <button className="btn" type="button" onClick={() => setRoutes({ ...routes, added: [...routes.added, newRoute] })}>
          + Route
        </button>
        <button className="btn" type="button" onClick={() => setRules({ ...rules, added: [...rules.added, newRule] })}>
          + Rule
        </button>
      </div>
      <div className="scroll-x">
        <table className="tbl" aria-label="Static routes">
          <thead>
            <tr>
              <th>Interface</th>
              <th>Target</th>
              <th>Gateway</th>
              <th>Metric</th>
              <th>Table</th>
              <th>On</th>
              <th>
                <span className="sr-only">Delete</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {state.routes
              .filter((r) => r.kind === routeKind)
              .map((r) => {
                const label = `route ${r.target}`
                const isDeleted = routes.deleted.includes(r.section)
                return routeLine(routes.edited[r.section] ?? routeOf(r), label, (row) => setRoutes({ ...routes, edited: { ...routes.edited, [r.section]: row } }), {
                  text: isDeleted ? 'Keep' : 'Delete',
                  label: `Delete ${label}`,
                  pressed: isDeleted,
                  onClick: () => setRoutes({ ...routes, deleted: toggled(routes.deleted, r.section) }),
                })
              })}
            {routes.added.map((row, i) =>
              row.kind !== routeKind
                ? null
                : routeLine(row, `new route ${i + 1}`, (next) => setRoutes({ ...routes, added: routes.added.map((x, n) => (n === i ? next : x)) }), {
                    text: 'Remove',
                    label: `Remove new route ${i + 1}`,
                    onClick: () => setRoutes({ ...routes, added: routes.added.filter((_, n) => n !== i) }),
                  }),
            )}
          </tbody>
        </table>
        <table className="tbl" aria-label="Rules">
          <thead>
            <tr>
              <th>Priority</th>
              <th>From</th>
              <th>To</th>
              <th>In</th>
              <th>Out</th>
              <th>Lookup</th>
              <th>On</th>
              <th>
                <span className="sr-only">Delete</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {state.rules
              .filter((r) => r.kind === ruleKind)
              .map((r) => {
                const label = `rule ${r.priority ?? r.section}`
                const isDeleted = rules.deleted.includes(r.section)
                return ruleLine(rules.edited[r.section] ?? ruleOf(r), label, (row) => setRules({ ...rules, edited: { ...rules.edited, [r.section]: row } }), {
                  text: isDeleted ? 'Keep' : 'Delete',
                  label: `Delete ${label}`,
                  pressed: isDeleted,
                  onClick: () => setRules({ ...rules, deleted: toggled(rules.deleted, r.section) }),
                })
              })}
            {rules.added.map((row, i) =>
              row.kind !== ruleKind
                ? null
                : ruleLine(row, `new rule ${i + 1}`, (next) => setRules({ ...rules, added: rules.added.map((x, n) => (n === i ? next : x)) }), {
                    text: 'Remove',
                    label: `Remove new rule ${i + 1}`,
                    onClick: () => setRules({ ...rules, added: rules.added.filter((_, n) => n !== i) }),
                  }),
            )}
          </tbody>
        </table>
      </div>
      {isBadRow && <div className="note x">Metric and priority are whole numbers.</div>}
      <NetChange change={change} short={shortName(routerName, routerId)} helpTopic={HELP.netRoutes} show={body !== null} />
      <LiveRoutes routerId={routerId} family={family} />
    </section>
  )
}
