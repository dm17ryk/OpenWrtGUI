import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { SshInstance, SshInstanceIn, SystemAccessState } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

/** One row as the screen edits it: the port as typed, and the name it is shown and labelled with. */
type Row = Omit<SshInstanceIn, 'port'> & { name: string; port: string }
type Flag = 'enable' | 'password_auth' | 'root_password_auth' | 'gateway_ports'

const rowOf = (i: SshInstance): Row => ({
  section: i.section,
  name: i.section,
  enable: i.enable,
  port: String(i.port),
  interface: i.interface,
  password_auth: i.password_auth,
  root_password_auth: i.root_password_auth,
  gateway_ports: i.gateway_ports,
})

const PORT = /^\d{1,5}$/

function changed(row: Row, old: SshInstance | undefined): boolean {
  if (!old) return true
  return (
    row.enable !== old.enable ||
    Number(row.port) !== old.port ||
    row.interface !== old.interface ||
    row.password_auth !== old.password_auth ||
    row.root_password_auth !== old.root_password_auth ||
    row.gateway_ports !== old.gateway_ports
  )
}

const toIn = ({ section, enable, port, interface: where, password_auth, root_password_auth, gateway_ports }: Row): SshInstanceIn => ({
  section,
  enable,
  port: Number(port),
  interface: where,
  password_auth,
  root_password_auth,
  gateway_ports,
})

type Props = { routerId: string; short: string; access: SystemAccessState }

/** dropbear's instances (D4). The app's own instance stays on, stays, and keeps listening where the app is. */
export function SshCard({ routerId, short, access }: Props) {
  const client = useQueryClient()
  const [seen, setSeen] = useState(access.ssh)
  const [rows, setRows] = useState<Row[]>(() => access.ssh.map(rowOf))
  const [removed, setRemoved] = useState<string[]>([])
  const [added, setAdded] = useState(0)
  if (seen !== access.ssh) {
    // the router's SSH settings changed (an apply, a read again): start from them
    setSeen(access.ssh)
    setRows(access.ssh.map(rowOf))
    setRemoved([])
  }
  const old = new Map(access.ssh.map((i) => [i.section, i]))
  const edits = rows.filter((r) => !removed.includes(r.name) && changed(r, r.section ? old.get(r.section) : undefined))
  const unready = edits.filter((r) => !PORT.test(r.port))
  const body = (edits.length > 0 || removed.length > 0) && unready.length === 0 ? { instances: edits.map(toIn), remove: removed } : null
  const change = usePlanApply(`/api/routers/${routerId}/system/ssh`, body, () => {
    void client.invalidateQueries({ queryKey: ['system-access', routerId] })
  })
  const update = (name: string, patch: Partial<Row>): void => setRows(rows.map((r) => (r.name === name ? { ...r, ...patch } : r)))
  const add = (): void => {
    const name = `new ${added + 1}`
    setAdded(added + 1)
    setRows([...rows, { section: null, name, enable: true, port: '', interface: '', password_auth: true, root_password_auth: true, gateway_ports: false }])
  }
  const drop = (row: Row): void => {
    if (row.section === null) setRows(rows.filter((r) => r.name !== row.name))
    else setRemoved(removed.includes(row.name) ? removed.filter((n) => n !== row.name) : [...removed, row.name])
  }
  const flag = (row: Row, key: Flag, label: string, isLocked = false) => (
    <input type="checkbox" aria-label={`${label} ${row.name}`} checked={row[key]} disabled={isLocked} onChange={(e) => update(row.name, { [key]: e.target.checked })} />
  )
  return (
    <section className="card stack" aria-labelledby="system-ssh-h">
      <div className="hrow">
        <h2 id="system-ssh-h">SSH access</h2>
        <Help topic={HELP.systemSsh} />
      </div>
      <div className="scroll-x">
        <table className="tbl" aria-label="SSH instances">
          <thead>
            <tr>
              <th>Instance</th>
              <th>On</th>
              <th>Port</th>
              <th>Interface</th>
              <th>Password logins</th>
              <th>Root password logins</th>
              <th>Gateway ports</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const isApp = row.section !== null && row.section === access.app_instance
              const choices = isApp ? ['', ...(access.app_interface ? [access.app_interface] : [])] : ['', ...access.interfaces]
              if (!choices.includes(row.interface)) choices.push(row.interface)
              const isGone = removed.includes(row.name)
              return (
                <tr key={row.name} className={isGone ? 'flag' : undefined}>
                  <td>
                    <span className="mono">{row.name}</span>
                    {isApp && <div className="muted">The app connects here</div>}
                    {isGone && <div className="muted">removed at Apply</div>}
                  </td>
                  <td>{flag(row, 'enable', 'Enable', isApp)}</td>
                  <td>
                    <input className="in mono" type="number" min={1} max={65535} style={{ width: 90 }} aria-label={`Port of ${row.name}`} value={row.port} onChange={(e) => update(row.name, { port: e.target.value })} />
                  </td>
                  <td>
                    <select className="in" aria-label={`Interface of ${row.name}`} value={row.interface} onChange={(e) => update(row.name, { interface: e.target.value })}>
                      {choices.map((c) => (
                        <option key={c} value={c}>
                          {c === '' ? 'All interfaces' : c}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>{flag(row, 'password_auth', 'Password logins on')}</td>
                  <td>{flag(row, 'root_password_auth', 'Root password logins on')}</td>
                  <td>{flag(row, 'gateway_ports', 'Gateway ports on')}</td>
                  <td>
                    <button type="button" className="btn" aria-label={`${isGone ? 'Keep' : 'Remove'} ${row.name}`} disabled={isApp} onClick={() => drop(row)}>
                      {isGone ? 'Keep' : 'Remove'}
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="row">
        <button type="button" className="btn" onClick={add}>
          Add instance
        </button>
      </div>
      {unready.map((r) => (
        <div key={r.name} className="note">
          Type a port (1-65535) for {r.name}.
        </div>
      ))}
      <NetChange change={change} short={short} helpTopic={HELP.systemSsh} show={body !== null} />
    </section>
  )
}
