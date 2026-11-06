import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { apiFetch } from '../../api/client'
import type { InterfaceIn, InterfaceView, NetApplyResult, NetworkState, OptionRow } from '../../api/types'
import { CheckList } from '../../components/CheckList'
import { OptionsTable } from '../../components/OptionsTable'
import { editsBody } from '../../components/options'
import { PreviewApply } from '../../components/PreviewApply'
import { usePlanApply } from '../../components/usePlanApply'
import { HELP } from '../../help/topics'
import { interfaceDraft, interfaceRequest } from './draft'
import { RollbackWait } from './NetChange'
import { words } from './rows'

type Props = {
  routerId: string
  routerName: string
  host: string
  view: InterfaceView
  state: NetworkState
  onApplied: (result: NetApplyResult) => void
}

/** One interface: its protocol and the hand-laid fields, All options from its protocol handler, one preview. */
export function InterfaceEditor({ routerId, routerName, host, view, state, onApplied }: Props) {
  const conf = view.conf
  const name = conf?.name ?? ''
  const short = routerName.split(' · ')[0] || routerId
  const [draft, setDraft] = useState(() => interfaceDraft(view, state.devices))
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [showOptions, setShowOptions] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [startHost] = useState(host) // the record follows a moved router; say where it moved from here
  const rows = useQuery({
    queryKey: ['net-options', routerId, name],
    queryFn: () => apiFetch<OptionRow[]>(`/api/routers/${routerId}/network/interfaces/${encodeURIComponent(name)}/options`),
    enabled: showOptions,
  })
  const body = useMemo((): InterfaceIn | null => {
    if (deleting) return { name, delete: true }
    const req = interfaceRequest(view, draft, state.devices)
    const list = editsBody(edits, rows.data ?? [])
    if (!req && list.length === 0) return null
    return { ...(req ?? { name }), ...(list.length ? { edits: list } : {}) }
  }, [deleting, name, view, draft, state.devices, edits, rows.data])
  const change = usePlanApply(`/api/routers/${routerId}/network/interfaces`, body, onApplied)
  const bridge = state.devices.find((d) => d.name === conf?.device && d.type === 'bridge')
  const target = change.plan?.target_host ?? host
  const set = (patch: Partial<typeof draft>): void => setDraft({ ...draft, ...patch })

  return (
    <div className="card stack" aria-label={`Interface ${name}`}>
      <div className="row">
        <h3>{name}</h3>
        {view.own && <span className="b air">this app's connection</span>}
        <div className="spacer" />
        {!view.own && (
          <button className="btn danger" type="button" aria-pressed={deleting} onClick={() => setDeleting(!deleting)}>
            {deleting ? 'Keep this interface' : `Delete ${name}`}
          </button>
        )}
      </div>
      {!deleting && (
        <>
          <div className="seg" role="group" aria-label="Protocol">
            {state.protocols.map((p) => (
              <button key={p.name} type="button" className={draft.proto === p.name ? 'on' : ''} aria-pressed={draft.proto === p.name} onClick={() => set({ proto: p.name })}>
                {p.label}
              </button>
            ))}
          </div>
          {draft.proto === 'static' && (
            <div className="grid">
              <label className="field">
                <span>Address</span>
                <input className="in mono" aria-label="Address (address/prefix)" placeholder="192.168.1.2/24" value={draft.address} onChange={(e) => set({ address: e.target.value })} />
              </label>
              <label className="field">
                <span>Gateway</span>
                <input className="in mono" aria-label="Gateway" placeholder="none" value={draft.gateway} onChange={(e) => set({ gateway: e.target.value })} />
              </label>
              <label className="field">
                <span>DNS servers</span>
                <input className="in mono" aria-label="DNS servers" placeholder="none" value={draft.dns.join(' ')} onChange={(e) => set({ dns: words(e.target.value) })} />
              </label>
              <label className="field">
                <span>MTU</span>
                <input className="in mono" aria-label="MTU" inputMode="numeric" placeholder="default" value={draft.mtu} onChange={(e) => set({ mtu: e.target.value })} />
              </label>
            </div>
          )}
          {bridge && (
            <label className="field">
              <span>Bridge members of {bridge.name}</span>
              <input className="in mono" aria-label="Bridge members" value={draft.ports.join(' ')} onChange={(e) => set({ ports: words(e.target.value) })} />
            </label>
          )}
          <div className="row">
            <button className="btn" type="button" aria-expanded={showOptions} onClick={() => setShowOptions(!showOptions)}>
              {showOptions ? 'Hide all options' : 'Show all options'}
            </button>
            <span className="muted">every option of the {draft.proto} protocol, from the router's own list</span>
          </div>
          {showOptions && <OptionsTable rows={rows.data ?? []} edits={edits} onEdit={(key, value) => setEdits({ ...edits, [key]: value })} />}
        </>
      )}
      {(body || change.result) && (
        <div className="grid">
          <PreviewApply
            heading={`Commands that will run on ${short}`}
            lines={change.plan?.lines ?? []}
            warnings={change.plan?.warnings ?? []}
            error={change.error}
            isBusy={change.isBusy}
            applyLabel="Apply with rollback"
            onApply={() => void change.apply()}
            helpTopic={HELP.netRollback}
          />
          {change.isBusy && <RollbackWait router={routerName} target={target} />}
          {change.result && (
            <div className="stack" style={{ gap: 8 }}>
              <CheckList result={change.result} provenText="Applied and confirmed" />
              {change.result.host && change.result.host !== startHost && (
                <span className="muted">
                  {routerName} is now at {change.result.host}
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
