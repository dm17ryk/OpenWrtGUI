import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { channelSummary, type ChannelDraft } from './draft'

const mhz = (channel: number): number => (channel === 14 ? 2484 : 2407 + 5 * channel)

type Props = { draft: ChannelDraft; band: string; allowed: number[]; country: string; onChange: (d: ChannelDraft) => void }

export function ChannelCard({ draft, band, allowed, country, onChange }: Props) {
  const shown = band === '2g' ? Array.from({ length: 14 }, (_, i) => i + 1) : allowed
  const ticked = draft.kind === 'set' ? draft.channels : draft.kind === 'all' ? allowed : []
  const toggle = (channel: number): void => {
    const base = draft.kind === 'set' ? draft.channels : draft.kind === 'all' ? allowed : []
    const next = base.includes(channel) ? base.filter((c) => c !== channel) : [...base, channel]
    onChange({ kind: 'set', channels: next.sort((a, b) => a - b) })
  }
  const preset = (kind: 'auto' | 'all' | 'none', label: string) => (
    <button type="button" className={draft.kind === kind ? 'on' : ''} aria-pressed={draft.kind === kind} onClick={() => onChange({ kind, channels: [] })}>
      {label}
    </button>
  )
  return (
    <section className="card stack" aria-labelledby="channels-h">
      <div className="row">
        <div className="hrow">
          <h2 id="channels-h">Channels</h2>
          <Help topic={HELP.wifiChannels} />
        </div>
        <span className="b neu mono">{channelSummary(draft, allowed)}</span>
      </div>
      <div className="row">
        <div className="seg" role="group" aria-label="Channel preset">
          {preset('auto', 'Auto')}
          {preset('all', 'All')}
          {preset('none', 'None')}
        </div>
        <span className="muted">or tick channels: the router picks only among them</span>
      </div>
      <div className="chans">
        {shown.map((channel) => {
          const ok = allowed.includes(channel)
          const label = ok ? `Channel ${channel}, ${mhz(channel)} MHz` : `Channel ${channel}, not allowed in ${country}`
          return (
            <button
              key={channel}
              type="button"
              className={`chan${ticked.includes(channel) ? ' on' : ''}`}
              aria-pressed={ticked.includes(channel)}
              aria-label={label}
              disabled={!ok}
              onClick={() => toggle(channel)}
            >
              <strong>{channel}</strong>
              <span className="muted mono">{mhz(channel)}</span>
            </button>
          )
        })}
      </div>
      <div className="muted">
        The channel list and power limits come from the router for its country ({country}).
        {shown.some((c) => !allowed.includes(c)) && ` Channel ${shown.filter((c) => !allowed.includes(c)).join(', ')} is not allowed in ${country}.`}
      </div>
    </section>
  )
}
