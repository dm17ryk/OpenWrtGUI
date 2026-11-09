import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { apiFetch } from '../../api/client'
import type { NetApplyResult, NetworkState, OptionRow } from '../../api/types'
import { OptionsTable } from '../../components/OptionsTable'
import { editsBody } from '../../components/options'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'
import { initialDraft, optionRows, settingsBody, type Auth, type PdpType, type SettingsBody, type SettingsDraft } from './settings'

// src/openwrtgui/net/interfaces.py QMI_LOCKED["dhcp"] (v0.6a plan D8)
const DHCP_NOTE = "lte_4 must stay DHCP: the BM806C sends downlink only after a DHCP exchange binds this router's MAC"

type Props = { routerId: string; routerName: string; autoconnectNote: string; onApplied: (result: NetApplyResult) => void }

type FormProps = Props & { rows: OptionRow[]; auto: boolean }

function SettingsForm({ routerId, routerName, rows, auto, onApplied }: FormProps) {
  const short = routerName.split(' · ')[0] || routerId
  const [initial] = useState(() => initialDraft(rows, auto))
  const [draft, setDraft] = useState<SettingsDraft>(initial)
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [showOptions, setShowOptions] = useState(false)
  const shown = useMemo(() => optionRows(rows), [rows])
  const { body: fields, error } = settingsBody(initial, draft)
  const list = editsBody(edits, shown)
  const body: SettingsBody | null = error || (Object.keys(fields).length === 0 && list.length === 0) ? null : { ...fields, ...(list.length ? { edits: list } : {}) }
  const change = usePlanApply(`/api/routers/${routerId}/lte/settings`, body, (result) => {
    setDraft((d) => ({ ...d, password: '', pincode: '' })) // applied: never keep a secret in the form
    setEdits({})
    onApplied(result)
  })
  const set = (patch: Partial<SettingsDraft>): void => setDraft({ ...draft, ...patch })

  return (
    <>
      <div className="grid">
        <label className="field">
          <span>APN</span>
          <input className="in mono" aria-label="APN" value={draft.apn} onChange={(e) => set({ apn: e.target.value })} />
        </label>
        <label className="field">
          <span>Authentication</span>
          <select className="in" aria-label="Authentication" value={draft.auth} onChange={(e) => set({ auth: e.target.value as Auth })}>
            <option value="none">none</option>
            <option value="pap">PAP</option>
            <option value="chap">CHAP</option>
            <option value="both">PAP or CHAP</option>
          </select>
        </label>
        <label className="field">
          <span>User name</span>
          <input className="in mono" aria-label="User name" autoComplete="off" value={draft.username} onChange={(e) => set({ username: e.target.value })} />
        </label>
        <label className="field">
          <span>Password</span>
          <input className="in" aria-label="Password" type="password" autoComplete="new-password" placeholder="unchanged" value={draft.password} onChange={(e) => set({ password: e.target.value })} />
        </label>
        <label className="field">
          <span>SIM PIN</span>
          <input className="in" aria-label="SIM PIN" type="password" inputMode="numeric" autoComplete="off" placeholder="unchanged" value={draft.pincode} onChange={(e) => set({ pincode: e.target.value })} />
        </label>
        <label className="field">
          <span>PDP type</span>
          <select className="in" aria-label="PDP type" value={draft.pdptype} onChange={(e) => set({ pdptype: e.target.value as PdpType })}>
            <option value="ipv4">IPv4</option>
            <option value="ipv6">IPv6</option>
            <option value="ipv4v6">IPv4 and IPv6</option>
          </select>
        </label>
        <label className="field">
          <span>MTU</span>
          <input className="in mono" aria-label="MTU" inputMode="numeric" placeholder="default" value={draft.mtu} onChange={(e) => set({ mtu: e.target.value })} />
        </label>
        <label className="field">
          <span>Metric</span>
          <input className="in mono" aria-label="Metric" inputMode="numeric" placeholder="default" value={draft.metric} onChange={(e) => set({ metric: e.target.value })} />
        </label>
      </div>
      <div className="row">
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" checked={draft.auto} onChange={(e) => set({ auto: e.target.checked })} />
          Bring up at boot
        </label>
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" checked={draft.defaultroute} onChange={(e) => set({ defaultroute: e.target.checked })} />
          Default route
        </label>
      </div>
      {error && <div className="note x">{error}</div>}
      <div className="row">
        <button className="btn" type="button" aria-expanded={showOptions} onClick={() => setShowOptions(!showOptions)}>
          {showOptions ? 'Hide all options' : 'Show all options'}
        </button>
        <span className="muted">every option of the LTE interface, from the router's own list</span>
      </div>
      {showOptions && <OptionsTable rows={shown} edits={edits} onEdit={(key, value) => setEdits({ ...edits, [key]: value })} />}
      <NetChange change={change} short={short} helpTopic={HELP.netRollback} show={body !== null} />
    </>
  )
}

/** The LTE interface's settings through the interface plan with its 60 s rollback (v0.6a plan, "LTE rules"). */
export function SettingsCard(props: Props) {
  const { routerId, autoconnectNote } = props
  const rows = useQuery({
    queryKey: ['lte-options', routerId],
    queryFn: () => apiFetch<OptionRow[]>(`/api/routers/${routerId}/lte/settings/options`),
  })
  const net = useQuery({ queryKey: ['network', routerId], queryFn: () => apiFetch<NetworkState>(`/api/routers/${routerId}/network`) })
  const lte = net.data?.interfaces.find((v) => v.conf?.proto === 'qmi')?.conf
  const error = rows.error ?? net.error
  return (
    <section className="card stack" aria-labelledby="lte-settings-h">
      <div className="hrow">
        <h2 id="lte-settings-h">Settings</h2>
        <Help topic={HELP.lteSettings} />
      </div>
      <div className="note">{autoconnectNote}</div>
      <div className="note">{DHCP_NOTE}</div>
      {error && <div className="note x">{error.message}</div>}
      {rows.data && net.data ? <SettingsForm key={rows.dataUpdatedAt} {...props} rows={rows.data} auto={lte?.auto ?? true} /> : !error && <div className="muted">Reading the settings…</div>}
    </section>
  )
}
