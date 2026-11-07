import { type ReactNode, useState } from 'react'
import type { FaultsState } from '../../api/types'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import { type FaultDraft, type FaultKind, FLOWS, type Netem } from './faults'

type Props = { state: FaultsState; draft: FaultDraft; onChange: (d: FaultDraft) => void }

const DISTRIBUTIONS: readonly Netem['distribution'][] = ['uniform', 'normal', 'pareto', 'paretonormal']
const WIFI_ONLY = 'A switch port cannot disconnect a Wi-Fi station. For Wi-Fi use Deauth or AP down.'
// netem to the target needs a root qdisc that keeps it to the target's traffic (faults/compile.py)
const NO_BAND = ' · no prio or ets qdisc on this router'

function Layer({ id, tag, title, help, on, off, children }: { id: string; tag: string; title: string; help: string; on: boolean; off: string | null; children: ReactNode }) {
  return (
    <article className={`card stack layer${on ? ' on' : ''}${off ? ' off' : ''}`} aria-labelledby={`layer-${id}`}>
      <div className="hrow">
        <span className="tag">{tag}</span>
        <h3 id={`layer-${id}`}>{title}</h3>
        <Help topic={help} />
      </div>
      {off && <div className="note">{off}</div>}
      {children}
    </article>
  )
}

const num = (text: string): number => (text.trim() === '' ? 0 : Number(text))

/** The faults by layer (spec 7.7); picking one makes it the fault the preview below arms. */
export function FaultCards({ state, draft, onChange }: Props) {
  // what was typed, so "0." or "" can be on the way to a number
  const [typed, setTyped] = useState<Record<string, string>>({})
  const t = state.targets.find((x) => draft.target !== null && x.mac === draft.target.mac && x.ip === draft.target.ip)
  const wifi = t?.via != null && t.via !== 'wired'
  const none = draft.target === null
  const set = (patch: Partial<FaultDraft>): void => onChange({ ...draft, ...patch })
  const pick = (kind: FaultKind, patch: Partial<FaultDraft> = {}): void => set({ kind, ...patch })
  const off = (kind: FaultKind): string | null => state.unavailable[kind] ?? null
  const netem = (patch: Partial<Netem>): void => set({ netem: { ...draft.netem, ...patch } })
  const ports = state.ports?.managed ? state.ports.ports : []
  const port = ports.find((p) => p.num === draft.port)
  const wifiOff = off('deauth') ?? (none || wifi ? null : 'Pick a Wi-Fi station: these act on the access point it is joined to.')
  return (
    <div className="layers">
      <Layer id="l1" tag="L1" title="Link down" help={HELP.faultL1} on={draft.kind === 'link_down'} off={off('link_down')}>
        <span className="b neu">Ethernet only</span>
        <div>Real carrier loss on the target&apos;s switch port. Its network interface goes down.</div>
        {wifi && <div className="note">{WIFI_ONLY}</div>}
        <label className="field">
          <span>Switch port</span>
          <select className="in" value={draft.port ?? ''} onChange={(e) => set({ port: e.target.value === '' ? null : Number(e.target.value) })}>
            <option value="">the one the switch lists for the target</option>
            {ports.map((p) => (
              <option key={p.num} value={p.num} disabled={p.own}>
                {p.label}
                {p.own ? ` · ${p.lock ?? "carries this app's SSH"}` : ''}
              </option>
            ))}
          </select>
        </label>
        <HelpTip topic={HELP.faultL1}>
          <button className="btn" type="button" disabled={none || wifi || off('link_down') !== null} onClick={() => pick('link_down')}>
            Take {port ? port.label : 'the port'} down
          </button>
        </HelpTip>
      </Layer>
      <Layer id="l2" tag="L2" title="Isolate" help={HELP.faultL2} on={draft.kind === 'isolate'} off={off('isolate')}>
        <div>Link and carrier stay up; everything else dies, ARP included.</div>
        <HelpTip topic={HELP.faultL2}>
          <button className="btn" type="button" disabled={none || off('isolate') !== null} onClick={() => pick('isolate')}>
            Isolate target
          </button>
        </HelpTip>
      </Layer>
      <Layer id="l3" tag="L3" title="Block flows" help={HELP.faultL3} on={draft.kind === 'block'} off={off('block')}>
        <div className="seg" role="group" aria-label="Flow">
          {FLOWS.map((f) => (
            <button
              key={f}
              type="button"
              className={draft.kind === 'block' && draft.flow === f ? 'on' : ''}
              aria-pressed={draft.kind === 'block' && draft.flow === f}
              disabled={none || off('block') !== null}
              onClick={() => pick('block', { flow: f })}
            >
              {f}
            </button>
          ))}
        </div>
        <label className="field">
          <span>
            Loss · <span className="mono">{draft.loss} %</span> (100 = block)
          </span>
          <input type="range" min={1} max={100} value={draft.loss} onChange={(e) => set({ loss: Number(e.target.value) })} />
        </label>
        <div className="muted small">
          Installed ahead of fw4&apos;s ct state established accept, so it also hits a call already in progress. Success is reported only after the rule is
          proven in place.
        </div>
      </Layer>
      <Layer id="netem" tag="netem" title="Impair" help={HELP.faultNetem} on={draft.kind === 'netem'} off={off('netem')}>
        <span className="b neu">scoped to the target</span>
        <div className="grid2">
          {(
            [
              ['delay_ms', 'Delay ms'],
              ['jitter_ms', 'Jitter ms'],
              ['loss_pct', 'Loss %'],
              ['reorder_pct', 'Reorder %'],
              ['duplicate_pct', 'Duplicate %'],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className="field">
              <span>{label}</span>
              <input
                className="in mono"
                inputMode="decimal"
                value={typed[key] ?? String(draft.netem[key])}
                onChange={(e) => {
                  setTyped({ ...typed, [key]: e.target.value })
                  netem({ [key]: num(e.target.value) })
                }}
              />
            </label>
          ))}
          <label className="field">
            <span>Distribution</span>
            <select className="in" value={draft.netem.distribution} onChange={(e) => netem({ distribution: e.target.value as Netem['distribution'] })}>
              {DISTRIBUTIONS.map((d) => {
                const missing = d !== 'uniform' && !state.caps.distributions.includes(d)
                return (
                  <option key={d} value={d} disabled={missing}>
                    {missing ? `${d} · no table on this router` : d}
                  </option>
                )
              })}
            </select>
          </label>
          <label className="field">
            <span>Direction</span>
            <select className="in" value={draft.netem.direction} onChange={(e) => netem({ direction: e.target.value as Netem['direction'] })}>
              <option value="to" disabled={!state.caps.band}>
                to target{state.caps.band ? '' : NO_BAND}
              </option>
              <option value="from" disabled={!state.caps.ifb}>
                from target{state.caps.ifb ? '' : ' · no ifb on this router'}
              </option>
              <option value="both" disabled={!state.caps.ifb || !state.caps.band}>
                both{!state.caps.band ? NO_BAND : state.caps.ifb ? '' : ' · no ifb on this router'}
              </option>
            </select>
          </label>
        </div>
        <HelpTip topic={HELP.faultNetem}>
          <button className="btn" type="button" disabled={none || off('netem') !== null} onClick={() => pick('netem')}>
            Impair target
          </button>
        </HelpTip>
      </Layer>
      <Layer id="wifi" tag="Wi-Fi" title="Station and AP" help={HELP.faultWifi} on={['deauth', 'ban', 'ap_down'].includes(draft.kind ?? '')} off={wifiOff}>
        <div>Deauth kicks one station, which then re-joins: the Wi-Fi equivalent of pulling a cable. Block keeps it out for a while. AP down drops every station.</div>
        <label className="field">
          <span>Block for (s)</span>
          <input
            className="in mono"
            inputMode="numeric"
            value={typed.ban_s ?? String(draft.ban_s)}
            onChange={(e) => {
              setTyped({ ...typed, ban_s: e.target.value })
              set({ ban_s: num(e.target.value) })
            }}
          />
        </label>
        <div className="row">
          <button className="btn" type="button" disabled={none || wifiOff !== null} onClick={() => pick('deauth')}>
            Deauth {t?.mac ?? 'station'}
          </button>
          <button className="btn" type="button" disabled={none || wifiOff !== null} onClick={() => pick('ban')}>
            Block {draft.ban_s} s
          </button>
          <button className="btn" type="button" disabled={none || wifiOff !== null} onClick={() => pick('ap_down')}>
            AP down
          </button>
        </div>
      </Layer>
      <article className="card stack layer" aria-labelledby="layer-duration">
        <div className="hrow">
          <h3 id="layer-duration">Duration</h3>
          <Help topic={HELP.faultDuration} />
        </div>
        <div className="seg" role="group" aria-label="Duration">
          <button type="button" className={draft.hold ? '' : 'on'} aria-pressed={!draft.hold} onClick={() => set({ hold: false })}>
            Until cleared
          </button>
          <button type="button" className={draft.hold ? 'on' : ''} aria-pressed={draft.hold} onClick={() => set({ hold: true })}>
            Hold, then clear
          </button>
        </div>
        <label className="field">
          <span>Hold for (s)</span>
          <input
            className="in mono"
            inputMode="numeric"
            disabled={!draft.hold}
            value={typed.hold_s ?? String(draft.hold_s)}
            onChange={(e) => {
              setTyped({ ...typed, hold_s: e.target.value })
              set({ hold_s: num(e.target.value) })
            }}
          />
        </label>
        <div className="muted small">A timed fault is cleared by a timer on the router itself, so it ends on time even if this PC or the app goes away.</div>
      </article>
    </div>
  )
}
