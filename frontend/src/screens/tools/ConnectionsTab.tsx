import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch } from '../../api/client'
import type { Connections, SipAlg } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { type ConnectionFilter, type Proto, byProtocol, matches } from './connectionFilter'

const POLL_MS = 5000
const READ_CAP = 500 // `head -n 500 /proc/net/nf_conntrack`

function sipText(sip: SipAlg): string {
  if (sip.state === 'unknown') return 'SIP ALG unknown: this router has no fw4 ruleset'
  if (sip.state === 'off') return 'SIP ALG off'
  const zones = `zone${sip.zones.length === 1 ? '' : 's'} ${sip.zones.join(', ')}`
  const ports = sip.ports.length ? `, UDP port ${sip.ports.join(', ')}` : ''
  return `SIP ALG on: ${zones}${ports}`
}

function summary(c: Connections): string | null {
  if (c.total == null || c.limit == null) return null
  // the router sends at most 500 entries (AP2 has ~7 MB free RAM); the count is read a moment after the table, so
  // only a full read means the table was cut (final review I3)
  const capped = c.rows.length >= READ_CAP && c.total > c.rows.length ? `, showing the first ${READ_CAP}` : ''
  return `${c.total} connections of ${c.limit}${capped}`
}

function errorText(e: unknown): string {
  return e instanceof ApiError ? e.detail : String(e)
}

/**
 * Connections (spec 7.8 Phase 2, v1.2a R8-R9): the conntrack table every 5 s while the tab is open, filtered in
 * the page, and whether SIP ALG is on, read when the tab opens and on Refresh. Nothing here writes.
 */
export function ConnectionsTab({ routerId }: { routerId: string }) {
  const conns = useQuery({
    queryKey: ['tool-connections', routerId],
    queryFn: () => apiFetch<Connections>(`/api/routers/${routerId}/system/connections`),
    refetchInterval: POLL_MS,
    refetchIntervalInBackground: false,
  })
  const sip = useQuery({
    queryKey: ['sip-alg', routerId],
    queryFn: () => apiFetch<SipAlg>(`/api/routers/${routerId}/system/sip-alg`),
  })
  const [filter, setFilter] = useState<ConnectionFilter>({ text: '', proto: 'all', sipOnly: false })
  const data = conns.data
  const rows = data?.rows ?? []
  const shown = rows.filter((c) => matches(c, filter))
  const line = data ? summary(data) : null
  return (
    <section className="card stack" aria-labelledby="tool-conns-h">
      <div className="hrow">
        <h2 id="tool-conns-h">Connections</h2>
        <Help topic={HELP.toolsConnections} />
        <span className="spacer" />
        {sip.data && (
          <span className={`b chip ${sip.data.state === 'on' ? 'own' : 'neu'}`}>
            {sipText(sip.data)} <Help topic={HELP.toolsSipAlg} />
          </span>
        )}
        <button
          className="btn"
          type="button"
          disabled={sip.isFetching || conns.isFetching}
          onClick={() => {
            void sip.refetch()
            void conns.refetch()
          }}
        >
          Refresh
        </button>
      </div>
      {conns.error && <div className="note x">{errorText(conns.error)}</div>}
      {sip.error && <div className="note x">{errorText(sip.error)}</div>}
      {conns.isPending && <div className="muted">Reading the connection table…</div>}
      {data?.note && <div className="note">{data.note}</div>}
      {data && !data.note && (
        <>
          <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
            {line && <span>{line}</span>}
            <span className="muted">{byProtocol(rows).map(([p, n]) => `${p} ${n}`).join(' · ')}</span>
          </div>
          <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
            <label>
              Protocol{' '}
              <select value={filter.proto} onChange={(e) => setFilter({ ...filter, proto: e.target.value as Proto })}>
                <option value="all">All</option>
                <option value="tcp">TCP</option>
                <option value="udp">UDP</option>
                <option value="icmp">ICMP</option>
                <option value="other">Other</option>
              </select>
            </label>
            <input
              type="search"
              aria-label="Address or port"
              placeholder="Address or port"
              value={filter.text}
              onChange={(e) => setFilter({ ...filter, text: e.target.value })}
            />
            <label>
              <input
                type="checkbox"
                checked={filter.sipOnly}
                onChange={(e) => setFilter({ ...filter, sipOnly: e.target.checked })}
              />{' '}
              SIP only
            </label>
          </div>
          <div className="scroll-x">
            <table className="tbl" aria-label="Connections">
              <thead>
                <tr>
                  <th>Protocol</th>
                  <th>Source</th>
                  <th>Destination</th>
                  <th>State</th>
                  <th>Bytes</th>
                  <th>Helper</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((c, i) => (
                  // the table has no key of its own: the same pair can show twice in different states
                  // eslint-disable-next-line react/no-array-index-key
                  <tr key={i}>
                    <td>{c.proto}</td>
                    <td className="mono">{c.src ? `${c.src}${c.sport != null ? `:${c.sport}` : ''}` : '—'}</td>
                    <td className="mono">{c.dst ? `${c.dst}${c.dport != null ? `:${c.dport}` : ''}` : '—'}</td>
                    <td>{c.state ?? '—'}</td>
                    <td className="mono">{c.bytes}</td>
                    <td>{c.helper ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
