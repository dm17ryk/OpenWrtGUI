import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError, apiFetch, postJson } from '../api/client'
import type { DescriptionSummary, RouterDetail } from '../api/types'
import { Help } from '../help/Help'
import { HELP } from '../help/topics'
import { RouterSections } from '../shell/RouterSections'

const FEATURE_ORDER = ['sae', 'owe', 'wps', '11r', '11ax', 'swconfig', 'firewall4', 'apk', 'wep', '11be']

function Source({ title, children, drives }: { title: string; children: ReactNode; drives: string }) {
  const id = `src-${title.replace(/[^a-z0-9]+/gi, '-')}`
  return (
    <article className="card stack" aria-labelledby={id} style={{ gap: 8, background: 'var(--surface2)' }}>
      <strong id={id} className="mono" style={{ fontSize: 13 }}>
        {title}
      </strong>
      <div style={{ fontSize: 13 }}>{children}</div>
      <div className="muted" style={{ fontSize: 12, marginTop: 'auto' }}>
        {drives}
      </div>
    </article>
  )
}

function Sources({ s }: { s: DescriptionSummary }) {
  const ports = Object.keys(s.port_labels).length
  const features = FEATURE_ORDER.filter((f) => f in s.features_on)
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
      <Source title="/etc/board.json" drives="drives the port labels and radio bands">
        {s.model} · {ports > 0 ? `${ports} switch ports with printed labels` : 'no switch description'}
      </Source>
      <Source title="ubus -v list" drives="decides which features are available">
        {s.services} services with their method signatures
      </Source>
      <Source title="network.wireless get_validate" drives="Wi-Fi › All options">
        {Object.entries(s.wireless_options).map(([radio, g]) => (
          <div key={radio}>
            {radio}: radio {g.device ?? 0} · SSID {g.interface ?? 0} · station {g.station ?? 0} · VLAN {g.vlan ?? 0}
          </div>
        ))}
      </Source>
      <Source title="network get_proto_handlers" drives="router addresses and LTE settings">
        {Object.entries(s.protocols)
          .map(([name, n]) => `${name} ${n}`)
          .join(' · ')}
      </Source>
      <Source title="luci getFeatures" drives="which Wi-Fi security choices are offered">
        <span className="row" style={{ gap: 6 }}>
          {features.map((f) => (
            <span key={f} className={s.features_on[f] ? 'b air' : 'b neu'}>
              {f} {s.features_on[f] ? 'yes' : 'no'}
            </span>
          ))}
        </span>
      </Source>
      <Source title="LuCI menu and ACL files" drives="the LuCI pages that open inside the app">
        {s.luci_packages} LuCI packages, {s.luci_menu_entries} menu entries
      </Source>
    </div>
  )
}

export function RouterOverview() {
  const { id = '' } = useParams()
  const client = useQueryClient()
  const [probeError, setProbeError] = useState<string | null>(null)
  const detail = useQuery({ queryKey: ['router', id], queryFn: () => apiFetch<RouterDetail>(`/api/routers/${id}`) })
  const d = detail.data

  const probe = async (): Promise<void> => {
    setProbeError(null)
    try {
      const summary = await postJson<DescriptionSummary>(`/api/routers/${id}/describe`)
      client.setQueryData<RouterDetail>(['router', id], (old) => (old ? { ...old, summary } : old))
    } catch (err) {
      setProbeError(err instanceof ApiError ? err.detail : String(err))
    }
  }

  if (detail.isError) {
    return (
      <main className="wrap">
        <div className="note x">{detail.error instanceof ApiError ? detail.error.detail : String(detail.error)}</div>
      </main>
    )
  }
  if (!d) {
    return (
      <main className="wrap">
        <div className="muted">Reading the router…</div>
      </main>
    )
  }

  const s = d.summary
  return (
    <main className="wrap">
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <div>
          <div className="eyebrow">
            <span className="mono">{d.record.host}</span>
            {s ? ` · ${s.model} · ${s.revision}` : ''}
          </div>
          <div className="hrow">
            <h1>{d.record.name}</h1>
            <Help topic={HELP.routerOverview} />
          </div>
        </div>
        <div className="spacer" />
        {d.record.auth === 'key' && (
          <>
            <button className="btn" type="button" onClick={() => void probe()}>
              Probe again
            </button>
            <Link className="btn" to={`/terminal/${d.record.id}`}>
              Open terminal
            </Link>
          </>
        )}
      </div>
      {d.record.auth === 'key' && <RouterSections routerId={d.record.id} name={d.record.name} current="overview" />}
      {probeError && <div className="note x">{probeError}</div>}
      {d.record.auth === 'none' ? (
        <div className="note w">
          This router needs the app key before the app can read it. <Link to={`/add?host=${encodeURIComponent(d.record.host)}`}>Install the key</Link>.
        </div>
      ) : (
        <section className="card stack" aria-labelledby="self-h">
          <div className="row">
            <div className="hrow">
              <h2 id="self-h">What {d.record.name.split(' · ')[0]} says about itself</h2>
              <Help topic={HELP.stepIdentify} />
            </div>
            <span className="muted">read on connect, the same sources LuCI uses</span>
          </div>
          {s ? <Sources s={s} /> : <div className="muted">Not read yet.</div>}
        </section>
      )}
      {s && Object.keys(s.port_labels).length > 0 && (
        <section className="card" aria-labelledby="ports-h">
          <h2 id="ports-h" style={{ marginBottom: 10 }}>
            Ports
          </h2>
          <div className="scroll-x">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Internal port</th>
                  <th>Printed label</th>
                  <th>Saved for this router</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(s.port_labels).map(([num, label]) => (
                  <tr key={num}>
                    <td className="mono">{num}</td>
                    <td>{label}</td>
                    <td>{d.record.port_labels[num] ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </main>
  )
}
