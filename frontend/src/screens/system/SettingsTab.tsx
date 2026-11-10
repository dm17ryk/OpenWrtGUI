import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch } from '../../api/client'
import type { SystemSettingsIn, SystemSettingsOut, TimeZones } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

type Draft = {
  hostname: string
  zonename: string
  ntpClient: boolean
  ntpServer: boolean
  ntpServers: string
  logSize: string
  logIp: string
  logPort: string
  logProto: 'udp' | 'tcp'
}

function draftOf(s: SystemSettingsOut): Draft {
  return {
    hostname: s.hostname ?? '',
    zonename: s.zonename ?? 'UTC',
    ntpClient: s.ntp_client ?? true,
    ntpServer: s.ntp_server ?? false,
    ntpServers: s.ntp_servers.join('\n'),
    logSize: s.log_size != null ? String(s.log_size) : '',
    logIp: s.log_ip ?? '',
    logPort: s.log_port != null ? String(s.log_port) : '',
    logProto: s.log_proto ?? 'udp',
  }
}

const servers = (text: string): string[] => text.split(/\s+/).filter(Boolean)
const num = (text: string): number => Number(text.trim())

/** Only what the user changed: the router checks every value and says what is wrong. */
function bodyOf(initial: Draft, d: Draft): SystemSettingsIn | null {
  const body: SystemSettingsIn = {}
  if (d.hostname !== initial.hostname) body.hostname = d.hostname.trim()
  if (d.zonename !== initial.zonename) body.zonename = d.zonename
  if (d.ntpClient !== initial.ntpClient) body.ntp_client = d.ntpClient
  if (d.ntpServer !== initial.ntpServer) body.ntp_server = d.ntpServer
  if (servers(d.ntpServers).join(' ') !== servers(initial.ntpServers).join(' ')) body.ntp_servers = servers(d.ntpServers)
  if (d.logSize !== initial.logSize && d.logSize.trim()) body.log_size = num(d.logSize)
  if (d.logIp !== initial.logIp) body.log_ip = d.logIp.trim()
  if (d.logIp.trim() && d.logPort !== initial.logPort && d.logPort.trim()) body.log_port = num(d.logPort)
  if (d.logIp.trim() && d.logProto !== initial.logProto) body.log_proto = d.logProto
  return Object.keys(body).length > 0 ? body : null
}

type FormProps = { routerId: string; short: string; settings: SystemSettingsOut; zones: string[] }

function SettingsForm({ routerId, short, settings, zones }: FormProps) {
  const client = useQueryClient()
  const [initial, setInitial] = useState(() => draftOf(settings))
  const [draft, setDraft] = useState<Draft>(initial)
  const [find, setFind] = useState('')
  const body = bodyOf(initial, draft)
  // applied: what the router has now is the new baseline; the form stays mounted so the proof stays on screen
  const change = usePlanApply(`/api/routers/${routerId}/system/settings`, body, () => {
    setInitial(draft)
    void client.invalidateQueries({ queryKey: ['system', routerId] })
  })
  const set = (patch: Partial<Draft>): void => setDraft({ ...draft, ...patch })
  const needle = find.trim().toLowerCase()
  const listed = zones.filter((z) => z === 'UTC' || z === draft.zonename || !needle || z.toLowerCase().includes(needle))
  return (
    <>
      <div className="grid">
        <label className="field">
          <span>Host name</span>
          <input className="in mono" value={draft.hostname} maxLength={63} onChange={(e) => set({ hostname: e.target.value })} />
        </label>
        <div className="field">
          <label className="field">
            <span>Find a time zone</span>
            <input className="in" type="search" value={find} onChange={(e) => setFind(e.target.value)} placeholder="Europe, Jerusalem…" />
          </label>
          <label className="field">
            <span>Time zone</span>
            <select className="in" value={draft.zonename} onChange={(e) => set({ zonename: e.target.value })}>
              {listed.map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="field">
          <span>NTP servers</span>
          <textarea className="in mono" rows={4} value={draft.ntpServers} onChange={(e) => set({ ntpServers: e.target.value })} />
        </label>
        <label className="field">
          <span>Log buffer (KiB)</span>
          <input className="in mono" inputMode="numeric" value={draft.logSize} onChange={(e) => set({ logSize: e.target.value })} />
        </label>
        <label className="field">
          <span>Remote syslog server</span>
          <input className="in mono" placeholder="none" value={draft.logIp} onChange={(e) => set({ logIp: e.target.value })} />
        </label>
        <label className="field">
          <span>Remote syslog port</span>
          <input className="in mono" inputMode="numeric" placeholder="514" value={draft.logPort} disabled={!draft.logIp.trim()} onChange={(e) => set({ logPort: e.target.value })} />
        </label>
        <label className="field">
          <span>Remote syslog protocol</span>
          <select className="in" value={draft.logProto} disabled={!draft.logIp.trim()} onChange={(e) => set({ logProto: e.target.value as Draft['logProto'] })}>
            <option value="udp">UDP</option>
            <option value="tcp">TCP</option>
          </select>
        </label>
      </div>
      <div className="row">
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" checked={draft.ntpClient} onChange={(e) => set({ ntpClient: e.target.checked })} />
          Set the time from NTP
        </label>
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" checked={draft.ntpServer} onChange={(e) => set({ ntpServer: e.target.checked })} />
          Serve the time to the network (NTP server)
        </label>
      </div>
      <NetChange change={change} short={short} helpTopic={HELP.systemSettings} show={body !== null} />
    </>
  )
}

type Props = { routerId: string; routerName: string }

/** Host name, time zone, NTP and the log through the plain uci apply (D5). */
export function SettingsTab({ routerId, routerName }: Props) {
  const short = routerName.split(' · ')[0] || routerId
  const settings = useQuery({ queryKey: ['system-settings', routerId], queryFn: () => apiFetch<SystemSettingsOut>(`/api/routers/${routerId}/system/settings`) })
  const zones = useQuery({ queryKey: ['system-zones', routerId], queryFn: () => apiFetch<TimeZones>(`/api/routers/${routerId}/system/timezones`) })
  const error = settings.error ?? zones.error
  return (
    <section className="card stack" aria-labelledby="system-settings-h">
      <div className="hrow">
        <h2 id="system-settings-h">System and time</h2>
        <Help topic={HELP.systemSettings} />
      </div>
      {zones.data?.note && <div className="note">{zones.data.note}</div>}
      {error && <div className="note x">{error instanceof ApiError ? error.detail : error.message}</div>}
      {settings.data && zones.data ? (
        <SettingsForm routerId={routerId} short={short} settings={settings.data} zones={zones.data.zones} />
      ) : (
        !error && <div className="muted">Reading the settings…</div>
      )}
    </section>
  )
}
