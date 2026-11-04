import { Link } from 'react-router'
import type { RouterItem } from '../api/types'
import { HelpTip } from '../help/Help'
import { HELP } from '../help/topics'
import { dbm, plural, radioText, routerState, stationCount, type RouterState } from './routerState'

const BADGE: Record<RouterState, string> = {
  'on air': 'b air',
  parked: 'b park',
  unreachable: 'b bad',
  'needs app key': 'b neu',
  connecting: 'b neu',
}

export function RouterCard({ item }: { item: RouterItem }) {
  const { record, status, summary } = item
  const state = routerState(item)
  const radio = status?.radios[0]
  const stations = stationCount(status)
  const first = status?.radios.flatMap((r) => r.stations)[0]
  const lan = status?.interfaces.find((i) => i.name === 'lan')
  const titleId = `card-${record.id}`
  return (
    <article className="card stack" aria-labelledby={titleId}>
      <div className="row" style={{ gap: 10 }}>
        <h3 id={titleId} style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>
          {record.name}
        </h3>
        <span className="mono muted">{record.host}</span>
        <div className="spacer" />
        <HelpTip topic={HELP.routerCards}>
          <span className={BADGE[state]}>{state}</span>
        </HelpTip>
      </div>
      {summary && (
        <div style={{ fontSize: 13, color: 'var(--ink2)' }}>
          {summary.model} · <span className="mono">{summary.revision}</span>
        </div>
      )}
      <dl className="kv">
        {radio && (
          <>
            <dt>Radio</dt>
            <dd className="mono">
              {radioText(radio)}
              {radio.up && radio.ssids[0] ? ` · ${radio.ssids[0].name} · ${radio.ssids[0].encryption}` : ''}
            </dd>
          </>
        )}
        {status && (
          <>
            <dt>Stations</dt>
            <dd>
              {stations === 0 ? '—' : plural(stations, 'station')}
              {first && (
                <span className="mono">
                  {' '}
                  · {dbm(first.signal_dbm)} · TX {first.tx_mbps} · RX {first.rx_mbps}
                </span>
              )}
            </dd>
          </>
        )}
        {lan && (
          <>
            <dt>Network</dt>
            <dd className="mono">
              lan {lan.ipv4[0] ?? 'no address'} · DHCP server {status?.dhcp_server_on ? 'on' : 'off'}
            </dd>
          </>
        )}
        {state === 'unreachable' && (
          <>
            <dt>Problem</dt>
            <dd>{item.health.error}</dd>
          </>
        )}
        <dt>Login</dt>
        <dd>
          {record.auth === 'key' ? (
            'app key · host key pinned'
          ) : (
            <>
              no app key yet · <Link to={`/add?host=${encodeURIComponent(record.host)}`}>Install key</Link>
            </>
          )}
        </dd>
      </dl>
      <div className="row" style={{ gap: 8 }}>
        <Link className="btn" to={`/routers/${record.id}`}>
          Open {record.name.split(' · ')[0]}
        </Link>
        {record.auth === 'key' && (
          <Link className="btn" to={`/terminal/${record.id}`}>
            Terminal
          </Link>
        )}
      </div>
    </article>
  )
}
