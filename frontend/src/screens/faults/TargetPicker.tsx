import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { apiFetch, putJson } from '../../api/client'
import type { FaultTarget, FaultsState, Settings } from '../../api/types'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import type { TargetRef } from './faults'

type Props = { state: FaultsState; short: string; target: TargetRef | null; onPick: (t: TargetRef | null) => void }

function linkText(t: FaultTarget): string {
  if (t.via === 'wired') return 'Ethernet'
  return t.via ? `Wi-Fi ${t.via}` : 'link unknown'
}

const same = (t: FaultTarget, ref: TargetRef | null): boolean => ref !== null && t.mac === ref.mac && t.ip === ref.ip

/** Who the fault hits: a host the router knows, or any IP / MAC, which can be remembered as a known device. */
export function TargetPicker({ state, short, target, onPick }: Props) {
  const client = useQueryClient()
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => apiFetch<Settings>('/api/settings') })
  const [other, setOther] = useState<{ ip: string; mac: string } | null>(null)
  const [remember, setRemember] = useState('')
  const [saved, setSaved] = useState<string | null>(null)
  const setOtherField = (patch: Partial<{ ip: string; mac: string }>): void => {
    const next = { ip: '', mac: '', ...other, ...patch }
    setOther(next)
    onPick(next.ip.trim() || next.mac.trim() ? { ip: next.ip.trim() || null, mac: next.mac.trim().toLowerCase() || null } : null)
  }
  const mac = target?.mac ?? null
  const save = async (): Promise<void> => {
    const s = settings.data
    const name = remember.trim()
    if (!s || !mac || !name) return
    const devices = s.known_devices ?? []
    const found = devices.find((d) => d.name === name)
    const known_devices = found
      ? devices.map((d) => (d === found ? { ...d, macs: d.macs.includes(mac) ? d.macs : [...d.macs, mac] } : d))
      : [...devices, { name, macs: [mac] }]
    client.setQueryData(['settings'], await putJson<Settings>('/api/settings', { ...s, known_devices }))
    setSaved(`${mac} is remembered as ${name}.`)
    setRemember('')
  }
  return (
    <section className="card stack" aria-labelledby="fault-target-h">
      <div className="hrow">
        <h2 id="fault-target-h">Target</h2>
        <Help topic={HELP.faultTarget} />
      </div>
      <div className="seg" role="group" aria-label="Fault target">
        {state.targets.map((t) => (
          <button
            key={`${t.mac} ${t.ip}`}
            type="button"
            className={other === null && same(t, target) ? 'on' : ''}
            aria-pressed={other === null && same(t, target)}
            onClick={() => {
              setOther(null)
              onPick({ mac: t.mac, ip: t.ip })
            }}
          >
            {t.name ?? t.mac ?? t.ip} · {t.ip ?? 'no IPv4'} · {linkText(t)}
          </button>
        ))}
        <button type="button" className={other !== null ? 'on' : ''} aria-pressed={other !== null} onClick={() => setOtherField({})}>
          other IP / MAC…
        </button>
      </div>
      {other !== null && (
        <div className="grid">
          <label className="field">
            <span>IP</span>
            <input className="in mono" value={other.ip} onChange={(e) => setOtherField({ ip: e.target.value })} />
          </label>
          <label className="field">
            <span>MAC</span>
            <input className="in mono" value={other.mac} onChange={(e) => setOtherField({ mac: e.target.value })} />
          </label>
        </div>
      )}
      {mac && (
        <div className="row">
          <label className="field">
            <span>Remember as</span>
            <input className="in" value={remember} onChange={(e) => setRemember(e.target.value)} />
          </label>
          <HelpTip topic={HELP.faultTarget}>
            <button className="btn" type="button" disabled={!remember.trim() || !settings.data} onClick={() => void save()}>
              Remember
            </button>
          </HelpTip>
          {saved && <span className="muted small">{saved}</span>}
        </div>
      )}
      <div className="muted">
        Found from {short}&apos;s Wi-Fi stations, DHCP leases and address table, and the known devices in Settings. The panel&apos;s Ethernet and Wi-Fi MACs
        are unrelated (W5500 vs ESP32 efuse), so matching by vendor prefix would miss one of them.
      </div>
    </section>
  )
}
