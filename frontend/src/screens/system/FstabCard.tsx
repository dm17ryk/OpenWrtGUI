import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { BlockDevice, FstabEntry, FstabGlobal, FstabState } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

type Props = { routerId: string; short: string; state: FstabState }
type Flag = 'auto_mount' | 'auto_swap' | 'anon_mount' | 'anon_swap' | 'check_fs'

const FLAGS: [Flag, string][] = [
  ['auto_mount', 'Mount automatically (auto_mount)'],
  ['auto_swap', 'Swap automatically (auto_swap)'],
  ['anon_mount', 'Mount devices fstab does not list (anon_mount)'],
  ['anon_swap', 'Swap on devices fstab does not list (anon_swap)'],
  ['check_fs', 'Check file systems before mounting (check_fs)'],
]

const blank = (kind: 'mount' | 'swap'): FstabEntry => ({
  section: null,
  kind,
  enabled: true,
  uuid: null,
  label: null,
  device: null,
  target: kind === 'mount' ? '/mnt/' : null,
  fstype: null,
  options: null,
})

/** The device an entry names now, as LuCI matches it: UUID (any case), then label, then device. */
function presentDevice(e: FstabEntry, devices: BlockDevice[]): BlockDevice | undefined {
  return (
    devices.find((d) => e.uuid && d.uuid && d.uuid.toLowerCase() === e.uuid.toLowerCase()) ??
    devices.find((d) => !e.uuid && e.label && d.label === e.label) ??
    devices.find((d) => !e.uuid && !e.label && e.device && d.dev === e.device)
  )
}

const deviceLabel = (d: BlockDevice): string => [d.dev, d.label, d.type].filter(Boolean).join(' · ')

/** LuCI's Mount Points page with block-mount (v1.0a2 D5): fstab's settings and entries, Generate, Mount all. */
export function FstabCard({ routerId, short, state }: Props) {
  const client = useQueryClient()
  const [settings, setSettings] = useState<FstabGlobal | null>(null)
  const [entries, setEntries] = useState<FstabEntry[] | null>(null)
  const [action, setAction] = useState<'generate' | 'mount' | null>(null)
  const done = (): void => {
    setSettings(null)
    setEntries(null)
    setAction(null)
    void client.invalidateQueries({ queryKey: ['system-fstab', routerId] })
    void client.invalidateQueries({ queryKey: ['system-mounts', routerId] })
  }
  const base = `/api/routers/${routerId}/system/fstab`
  const body = settings || entries ? { settings, entries } : null
  const edit = usePlanApply(base, body, done)
  const run = usePlanApply(action ? `${base}/${action}` : base, action ? {} : null, done)
  const shownSettings = settings ?? state.settings
  const rows = entries ?? state.entries
  const setRow = (i: number, patch: Partial<FstabEntry>): void => setEntries(rows.map((e, j) => (j === i ? { ...e, ...patch } : e)))
  const pick = (i: number, value: string): void => {
    const d = state.devices.find((x) => (x.uuid ?? x.dev) === value)
    if (d) setRow(i, d.uuid ? { uuid: d.uuid, label: null, device: null } : { uuid: null, label: null, device: d.dev })
  }
  return (
    <div className="stack">
      <h3>fstab</h3>
      {state.missing.length > 0 && <div className="note w">Could not read: {state.missing.join(', ')}.</div>}
      <fieldset className="stack">
        <legend>Settings</legend>
        {FLAGS.map(([key, label]) => (
          <label key={key} className="row">
            <input type="checkbox" checked={shownSettings[key]} onChange={(e) => setSettings({ ...shownSettings, [key]: e.target.checked })} />
            {label}
          </label>
        ))}
      </fieldset>
      <div className="scroll-x">
        <table className="tbl" aria-label="fstab entries">
          <thead>
            <tr>
              <th>Enabled</th>
              <th>Kind</th>
              <th>Device</th>
              <th>Mount point</th>
              <th>Type</th>
              <th>Options</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((e, i) => {
              const d = presentDevice(e, state.devices)
              const named = e.uuid ?? e.label ?? e.device ?? ''
              return (
                <tr key={e.section ?? `new-${i}`}>
                  <td>
                    <input type="checkbox" aria-label="Enabled" checked={e.enabled} onChange={(x) => setRow(i, { enabled: x.target.checked })} />
                  </td>
                  <td>{e.kind}</td>
                  <td>
                    <select aria-label="Device" value={d ? (d.uuid ?? d.dev) : named} onChange={(x) => pick(i, x.target.value)}>
                      {!d && <option value={named}>{named || 'choose a device'}</option>}
                      {state.devices.map((x) => (
                        <option key={x.dev} value={x.uuid ?? x.dev}>
                          {deviceLabel(x)}
                        </option>
                      ))}
                    </select>
                    {!d && named && <div className="muted">not present</div>}
                  </td>
                  <td>{e.kind === 'mount' && <input aria-label="Mount point" className="mono" value={e.target ?? ''} onChange={(x) => setRow(i, { target: x.target.value })} />}</td>
                  <td>{e.kind === 'mount' && <input aria-label="Type" className="mono" placeholder="auto" value={e.fstype ?? ''} onChange={(x) => setRow(i, { fstype: x.target.value || null })} />}</td>
                  <td>{e.kind === 'mount' && <input aria-label="Options" className="mono" placeholder="defaults" value={e.options ?? ''} onChange={(x) => setRow(i, { options: x.target.value || null })} />}</td>
                  <td>
                    <button type="button" className="btn" onClick={() => setEntries(rows.filter((_, j) => j !== i))}>
                      Remove
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="row">
        <button type="button" className="btn" onClick={() => setEntries([...rows, blank('mount')])}>
          Add mount
        </button>
        <button type="button" className="btn" onClick={() => setEntries([...rows, blank('swap')])}>
          Add swap
        </button>
        <span className="spacer" />
        <button type="button" className="btn" onClick={() => setAction('mount')}>
          Mount attached devices
        </button>
        <button type="button" className="btn" onClick={() => setAction('generate')}>
          Generate config
        </button>
      </div>
      <NetChange change={edit} short={short} helpTopic={HELP.systemMounts} show={body !== null} />
      <NetChange change={run} short={short} helpTopic={HELP.systemMounts} show={action !== null} />
    </div>
  )
}
