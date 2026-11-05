import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { ApiError, apiFetch, postJson } from '../../api/client'
import type { Station } from '../../api/types'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import { dbm } from '../routerState'

function duration(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return h > 0 ? `${h} h ${m} m` : `${m} m ${seconds % 60} s`
}

function who(s: Station): string {
  return [s.name, s.ip].filter(Boolean).join(' · ') || '—'
}

type Props = { routerId: string; short: string }

export function StationsTable({ routerId, short }: Props) {
  const client = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const stations = useQuery({
    queryKey: ['stations', routerId],
    queryFn: () => apiFetch<Station[]>(`/api/routers/${routerId}/wifi/stations`),
    refetchInterval: 5000,
  })
  const act = async (path: string, body?: unknown): Promise<void> => {
    setError(null)
    try {
      await postJson(path, body)
      await client.invalidateQueries({ queryKey: ['stations', routerId] })
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err))
    }
  }
  const block = (s: Station): void => {
    const answer = window.prompt(`Keep ${s.name ?? s.mac} out for how many seconds (10 to 3600)?`, '60')
    if (answer) void act(`/api/routers/${routerId}/wifi/stations/${s.mac}/block`, { seconds: Number(answer) })
  }
  const deauth = (s: Station): void => {
    if (window.confirm(`Disconnect ${s.name ?? s.mac}? It may join again at once.`)) {
      void act(`/api/routers/${routerId}/wifi/stations/${s.mac}/deauth`)
    }
  }
  const list = stations.data ?? []
  return (
    <section className="card stack" aria-labelledby="stations-h">
      <div className="row">
        <div className="hrow">
          <h2 id="stations-h">Stations on {short}</h2>
          <Help topic={HELP.wifiStations} />
        </div>
        <span className="muted">live from the router, with names from its host hints</span>
      </div>
      {error && (
        <div className="note x" role="alert">
          {error}
        </div>
      )}
      {list.length === 0 ? (
        <div className="muted">{stations.isLoading ? 'Reading…' : 'No station is connected.'}</div>
      ) : (
        <div className="scroll-x">
          <table className="tbl" aria-label="Stations">
            <thead>
              <tr>
                <th>Station</th>
                <th>Name / IP</th>
                <th>Signal</th>
                <th>TX rate</th>
                <th>RX rate</th>
                <th>Mode</th>
                <th>Connected</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.map((s) => (
                <tr key={s.mac}>
                  <td className="mono">{s.mac}</td>
                  <td>{who(s)}</td>
                  <td className="mono">{s.signal_dbm != null ? dbm(s.signal_dbm) : '—'}</td>
                  <td className="mono">{s.tx_mbps != null ? `${s.tx_mbps.toFixed(1)}${s.tx_mcs != null ? ` MCS ${s.tx_mcs}` : ''}` : '—'}</td>
                  <td className="mono">{s.rx_mbps != null ? s.rx_mbps.toFixed(1) : '—'}</td>
                  <td>{s.mode}</td>
                  <td>{duration(s.connected_s)}</td>
                  <td>
                    <div className="row" style={{ gap: 6, flexWrap: 'nowrap' }}>
                      <Link className="btn" to={`/routers/${routerId}/rf?station=${encodeURIComponent(s.mac)}`}>
                        RF
                      </Link>
                      <HelpTip topic={HELP.wifiStations}>
                        <button className="btn danger" type="button" onClick={() => block(s)}>
                          Block
                        </button>
                      </HelpTip>
                      <button className="btn danger" type="button" onClick={() => deauth(s)}>
                        Deauth
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
