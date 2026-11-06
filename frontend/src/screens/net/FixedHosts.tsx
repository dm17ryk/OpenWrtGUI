import { useState } from 'react'
import type { HostConf, HostIn, HostsIn, NetworkState } from '../../api/types'
import { Toggle } from '../../components/Toggle'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from './NetChange'
import { shortName, toggled, upsertsOf } from './rows'

export type HostRow = { section: string | null; name: string; mac: string; ip: string; leasetime: string; gets_address: boolean }

const emptyHost = (): HostRow => ({ section: null, name: '', mac: '', ip: '', leasetime: '', gets_address: true })

const rowOf = (h: HostConf): HostRow => ({
  section: h.section,
  name: h.name ?? '',
  mac: h.macs.join(' '),
  ip: h.ip ?? '',
  leasetime: h.leasetime ?? '',
  gets_address: h.gets_address,
})

function upsert(r: HostRow): HostIn {
  const opt = (key: 'name' | 'ip' | 'leasetime') => (r[key].trim() ? { [key]: r[key].trim() } : {})
  return { ...(r.section ? { section: r.section } : {}), mac: r.mac.trim(), ...opt('name'), ...opt('ip'), ...opt('leasetime'), gets_address: r.gets_address }
}

type RowProps = { row: HostRow; label: string; macLocked: boolean; deleted: boolean; onChange: (row: HostRow) => void; remove: { text: string; label: string; onClick: () => void } }

function HostLine({ row, label, macLocked, deleted, onChange, remove }: RowProps) {
  // Several MACs on one address cannot be edited as one field here: such a row can only be deleted.
  const locked = deleted || macLocked
  const field = (key: 'name' | 'mac' | 'ip' | 'leasetime', name: string, placeholder = '') => (
    <td>
      <input
        className="in mono"
        aria-label={`${name} of ${label}`}
        placeholder={placeholder}
        value={row[key]}
        disabled={locked}
        title={macLocked ? 'Several MACs share this address: change it in LuCI' : undefined}
        onChange={(e) => onChange({ ...row, [key]: e.target.value })}
      />
    </td>
  )
  return (
    <tr className={deleted ? 'muted' : undefined}>
      {field('name', 'Name')}
      {field('mac', 'MAC', 'aa:bb:cc:dd:ee:ff')}
      {field('ip', 'IP', 'any from the pool')}
      {field('leasetime', 'Lease time', 'default')}
      <td>
        <Toggle label={`${label} gets an address`} checked={row.gets_address} disabled={locked} onChange={(on) => onChange({ ...row, gets_address: on })} />
      </td>
      <td>
        <button className="btn danger" type="button" aria-label={remove.label} aria-pressed={deleted} onClick={remove.onClick}>
          {remove.text}
        </button>
      </td>
    </tr>
  )
}

type Props = {
  routerId: string
  routerName: string
  state: NetworkState
  added: HostRow[]
  onAdded: (rows: HostRow[]) => void
  onApplied: () => void
}

/** Fixed addresses by MAC (dhcp `host` sections): edit, add, delete, all in one preview. */
export function FixedHosts({ routerId, routerName, state, added, onAdded, onApplied }: Props) {
  const [edited, setEdited] = useState<Record<string, HostRow>>({})
  const [deleted, setDeleted] = useState<string[]>([])
  const upserts = upsertsOf(state.hosts, { edited, deleted, added }, rowOf, (r) => r.mac.trim() !== '').map(upsert)
  const body: HostsIn | null = upserts.length || deleted.length ? { upserts, deletes: deleted } : null
  const change = usePlanApply(`/api/routers/${routerId}/network/hosts`, body, () => {
    setEdited({})
    setDeleted([])
    onAdded([])
    onApplied()
  })
  return (
    <section className="card stack" aria-labelledby="hosts-h">
      <div className="row">
        <div className="hrow">
          <h2 id="hosts-h">Fixed addresses by MAC</h2>
          <Help topic={HELP.netHosts} />
        </div>
        <div className="spacer" />
        <button className="btn" type="button" onClick={() => onAdded([...added, emptyHost()])}>
          + Fixed address
        </button>
      </div>
      <div className="scroll-x">
        <table className="tbl" aria-label="Fixed addresses">
          <thead>
            <tr>
              <th>Name</th>
              <th>MAC</th>
              <th>IP</th>
              <th>Lease time</th>
              <th>Gets an address</th>
              <th>
                <span className="sr-only">Delete</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {state.hosts.map((h) => {
              const label = h.name || h.ip || h.section
              const isDeleted = deleted.includes(h.section)
              return (
                <HostLine
                  key={h.section}
                  row={edited[h.section] ?? rowOf(h)}
                  label={label}
                  macLocked={h.macs.length > 1}
                  deleted={isDeleted}
                  onChange={(row) => setEdited({ ...edited, [h.section]: row })}
                  remove={{ text: isDeleted ? 'Keep' : 'Delete', label: `Delete ${label}`, onClick: () => setDeleted(toggled(deleted, h.section)) }}
                />
              )
            })}
            {added.map((row, i) => (
              <HostLine
                key={`new-${i}`}
                row={row}
                label={`new address ${i + 1}`}
                macLocked={false}
                deleted={false}
                onChange={(next) => onAdded(added.map((r, n) => (n === i ? next : r)))}
                remove={{ text: 'Remove', label: `Remove new address ${i + 1}`, onClick: () => onAdded(added.filter((_, n) => n !== i)) }}
              />
            ))}
          </tbody>
        </table>
      </div>
      {state.hosts.length === 0 && added.length === 0 && <div className="muted">No fixed addresses: every device gets one from the pool.</div>}
      <NetChange change={change} short={shortName(routerName, routerId)} helpTopic={HELP.netHosts} show={body !== null} />
    </section>
  )
}
