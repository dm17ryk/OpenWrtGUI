import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch } from '../../api/client'
import type { AccessDevice, AccessIn, AccessState, SsidAccess } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from './NetChange'
import { shortName, toggled } from './rows'

type Policy = SsidAccess['policy']
type Method = NonNullable<AccessIn['method']>
type Action = { kind: 'block' | 'unblock'; device: AccessDevice }

const POLICIES: ReadonlyArray<readonly [Policy, string]> = [
  ['everyone', 'Everyone'],
  ['deny', 'Block listed'],
  ['allow', 'Only listed'],
]
const DEFAULT_SECONDS = 60
const label = (d: AccessDevice): string => d.name || d.mac

type ChangeProps = { base: string; short: string; sections: string[]; action: Action; onApplied: () => void }

/** Block or unblock one device on the ticked SSIDs: now, for N s, or saved. */
function DeviceChange({ base, short, sections, action, onApplied }: ChangeProps) {
  const [method, setMethod] = useState<Method>('now')
  const [seconds, setSeconds] = useState(String(DEFAULT_SECONDS))
  const n = Number(seconds)
  const methods: ReadonlyArray<readonly [Method, string]> = [
    ['now', 'Now · no Wi-Fi restart'],
    ...(action.kind === 'block' ? ([['timed', `For ${seconds || 'N'} s`]] as const) : []),
    ['saved', 'Saved'],
  ]
  const body: AccessIn | null = sections.length
    ? {
        kind: action.kind,
        sections,
        mac: action.device.mac,
        method,
        ...(method === 'timed' ? { seconds: Number.isInteger(n) ? n : 0 } : {}),
      }
    : null
  const change = usePlanApply(base, body, onApplied)
  return (
    <div className="card stack" aria-label={`${action.kind === 'block' ? 'Block' : 'Unblock'} ${label(action.device)}`}>
      <div className="row">
        <h3>
          {action.kind === 'block' ? 'Block' : 'Unblock'} {label(action.device)} <span className="muted mono">{action.device.mac}</span>
        </h3>
      </div>
      <div className="row">
        <div className="seg" role="group" aria-label="How">
          {methods.map(([m, text]) => (
            <button key={m} type="button" className={method === m ? 'on' : ''} aria-pressed={method === m} onClick={() => setMethod(m)}>
              {text}
            </button>
          ))}
        </div>
        {method === 'timed' && (
          <label className="row" style={{ gap: 6 }}>
            <input className="in mono" style={{ width: 90 }} type="number" min={10} max={3600} aria-label="Seconds" value={seconds} onChange={(e) => setSeconds(e.target.value)} />
            <span className="muted">10 to 3600 s</span>
          </label>
        )}
      </div>
      {method === 'now' && <div className="muted">Until the next Wi-Fi restart.</div>}
      <NetChange change={change} short={short} helpTopic={HELP.netAccess} show={body !== null} />
    </div>
  )
}

type Props = { routerId: string; routerName: string; onApplied: () => void }

/** Wi-Fi access by MAC (spec 7.4): who may join each SSID, and blocking one device now, for N s or saved. */
export function WifiAccess({ routerId, routerName, onApplied }: Props) {
  const client = useQueryClient()
  const base = `/api/routers/${routerId}/network/access`
  const access = useQuery({ queryKey: ['net-access', routerId], queryFn: () => apiFetch<AccessState>(base) })
  const ssids = access.data?.ssids ?? []
  const [unticked, setUnticked] = useState<string[]>([])
  const [policy, setPolicy] = useState<Policy | null>(null)
  const [action, setAction] = useState<Action | null>(null)
  const [extra, setExtra] = useState<AccessDevice[]>([])
  const [adding, setAdding] = useState({ open: false, mac: '', name: '' })
  const sections = ssids.map((s) => s.section).filter((s) => !unticked.includes(s))
  const current = new Set(ssids.filter((s) => sections.includes(s.section)).map((s) => s.policy))
  const shown = policy ?? (current.size === 1 ? [...current][0] : null)
  const applied = (): void => {
    setPolicy(null)
    void client.invalidateQueries({ queryKey: ['net-access', routerId] })
    onApplied()
  }
  const policyChange = usePlanApply(base, policy && sections.length ? { kind: 'policy', sections, policy } : null, applied)
  const short = shortName(routerName, routerId)
  const devices = [...(access.data?.devices ?? []), ...extra.filter((e) => !access.data?.devices.some((d) => d.mac === e.mac))]
  const ssidOf = (section: string): string => ssids.find((s) => s.section === section)?.ssid ?? section
  const addDevice = (): void => {
    const mac = adding.mac.trim().toLowerCase()
    if (mac) setExtra([...extra, { mac, name: adding.name.trim() || null, saved_in: [], blocked_now_on: [] }])
    setAdding({ open: false, mac: '', name: '' })
  }

  return (
    <section className="card stack" aria-labelledby="access-h" id="wifi-access">
      <div className="row">
        <div className="hrow">
          <h2 id="access-h">Wi-Fi access by MAC</h2>
          <Help topic={HELP.netAccess} />
        </div>
      </div>
      {access.isError && <div className="note x">{access.error instanceof ApiError ? access.error.detail : String(access.error)}</div>}
      {access.isSuccess && ssids.length === 0 && <div className="muted">This router has no SSIDs.</div>}
      {ssids.length > 0 && (
        <>
          <div className="row" role="group" aria-label="SSIDs">
            {ssids.map((s) => (
              <label key={s.section} className="row" style={{ gap: 6 }}>
                <input type="checkbox" aria-label={s.ssid} checked={!unticked.includes(s.section)} onChange={() => setUnticked(toggled(unticked, s.section))} />
                <span>{s.ssid}</span>
                <span className="muted mono">{s.radio}</span>
                {!s.ifname && <span className="b park">not on air</span>}
              </label>
            ))}
          </div>
          {sections.length === 0 && <div className="note w">Tick at least one SSID.</div>}
          <div className="seg" role="group" aria-label="Who may join">
            {POLICIES.map(([p, text]) => (
              <button key={p} type="button" className={shown === p ? 'on' : ''} aria-pressed={shown === p} onClick={() => setPolicy(p)}>
                {text}
              </button>
            ))}
          </div>
          <NetChange change={policyChange} short={short} helpTopic={HELP.netAccess} show={policy !== null && sections.length > 0} />
          <div className="row">
            <div className="eyebrow">Devices</div>
            <div className="spacer" />
            <button className="btn" type="button" aria-expanded={adding.open} onClick={() => setAdding({ ...adding, open: !adding.open })}>
              + Device
            </button>
          </div>
          {adding.open && (
            <div className="row">
              <input className="in mono" aria-label="New device MAC" placeholder="aa:bb:cc:dd:ee:ff" value={adding.mac} onChange={(e) => setAdding({ ...adding, mac: e.target.value })} />
              <input className="in" aria-label="New device name" placeholder="name (optional)" value={adding.name} onChange={(e) => setAdding({ ...adding, name: e.target.value })} />
              <button className="btn" type="button" onClick={addDevice}>
                Add
              </button>
            </div>
          )}
          <div className="scroll-x">
            <table className="tbl" aria-label="Devices">
              <thead>
                <tr>
                  <th>Device</th>
                  <th>MAC</th>
                  <th>Saved in</th>
                  <th>Blocked now on</th>
                  <th>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {devices.map((d) => (
                  <tr key={d.mac}>
                    <td>{d.name ?? '—'}</td>
                    <td className="mono">{d.mac}</td>
                    <td>{d.saved_in.map(ssidOf).join(', ') || '—'}</td>
                    <td className="mono">{d.blocked_now_on.join(', ') || '—'}</td>
                    <td>
                      <span className="row" style={{ gap: 6 }}>
                        <button className="btn" type="button" aria-label={`Block ${label(d)}`} onClick={() => setAction({ kind: 'block', device: d })}>
                          Block
                        </button>
                        <button className="btn" type="button" aria-label={`Unblock ${label(d)}`} onClick={() => setAction({ kind: 'unblock', device: d })}>
                          Unblock
                        </button>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {devices.length === 0 && <div className="muted">No device is listed or blocked: + Device adds one by MAC.</div>}
          {action && <DeviceChange key={`${action.kind}-${action.device.mac}`} base={base} short={short} sections={sections} action={action} onApplied={applied} />}
        </>
      )}
    </section>
  )
}
