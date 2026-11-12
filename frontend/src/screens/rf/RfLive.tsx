import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useParams, useSearchParams } from 'react-router'
import { apiFetch, openSocket } from '../../api/client'
import type { Bitrate, FrameState, RateRow, RfMessage, RfSample, RouterDetail, StationSample, WifiState } from '../../api/types'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import { RouterSections } from '../../shell/RouterSections'
import { dbm } from '../routerState'
import { ChannelAnalysis } from './ChannelAnalysis'
import { FrameAnalysis } from './FrameAnalysis'
import { RatesTable } from './RatesTable'
import { RfChart } from './RfChart'
import { pushSample, windowed, type Buffers, type WindowS } from './series'

const WINDOWS: ReadonlyArray<readonly [WindowS, string]> = [
  [60, '1 min'],
  [300, '5 min'],
  [3600, '1 h'],
]
const RATES_EVERY_MS = 5000

const fmt = (v: number | null | undefined, digits = 1): string => (v == null ? '—' : v.toFixed(digits))

function rateText(b: Bitrate | null): string {
  return b ? `${b.mbps.toFixed(1)} Mb/s` : '—'
}

function rateDetail(b: Bitrate | null): string {
  if (!b) return ''
  if (b.mcs === null) return b.mode === 'b' ? '802.11b CCK' : '802.11g OFDM'
  return `MCS ${b.mcs} · ${b.width_mhz === 40 ? 'HT40' : 'HT20'} · ${b.short_gi ? 'short' : 'long'} GI`
}

function Tile({ label, value, note, children }: { label: string; value: string; note: string; children?: ReactNode }) {
  return (
    <section className="card stack rf-tile" aria-label={label}>
      <span className="eyebrow">{label}</span>
      <strong className="mono">{value}</strong>
      {children}
      <span className="muted">{note}</span>
    </section>
  )
}

function Kv({ rows }: { rows: ReadonlyArray<readonly [string, string]> }) {
  return (
    <dl className="kv">
      {rows.map(([k, v]) => (
        <div key={k} style={{ display: 'contents' }}>
          <dt>{k}</dt>
          <dd className="mono">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

export function RfLive() {
  const { id = '' } = useParams()
  const [params] = useSearchParams()
  const radio = params.get('radio') ?? 'radio0'
  const detail = useQuery({ queryKey: ['router', id], queryFn: () => apiFetch<RouterDetail>(`/api/routers/${id}`) })
  const wifi = useQuery({ queryKey: ['wifi', id], queryFn: () => apiFetch<WifiState>(`/api/routers/${id}/wifi`) })
  const [buffers, setBuffers] = useState<Buffers>({})
  const [latest, setLatest] = useState<RfSample | null>(null)
  const [lastSeen, setLastSeen] = useState<Record<string, StationSample>>({})
  const [idle, setIdle] = useState<string | null>(null)
  const [paused, setPaused] = useState(false)
  const [windowS, setWindowS] = useState<WindowS>(300)
  const [chosen, setChosen] = useState<string | null>(params.get('station'))
  const [recording, setRecording] = useState<string | null>(null)
  const [rates, setRates] = useState<{ mac: string; rows?: RateRow[]; error?: string } | null>(null)
  const [frames, setFrames] = useState<FrameState | null>(null)
  const socket = useRef<WebSocket | null>(null)
  const pausedRef = useRef(paused)
  useEffect(() => {
    pausedRef.current = paused
  }, [paused])

  useEffect(() => {
    const ws = openSocket(`/ws/rf/${id}`, { radio })
    socket.current = ws
    ws.onmessage = (ev: MessageEvent<string>) => {
      const msg = JSON.parse(ev.data) as RfMessage
      if (msg.type === 'rf') {
        setIdle(null)
        if (pausedRef.current) return
        setLatest(msg.sample)
        setBuffers((b) => pushSample(b, msg.sample))
        setLastSeen((seen) => ({ ...seen, ...Object.fromEntries(msg.sample.stations.map((s) => [s.mac, s])) }))
      } else if (msg.type === 'rf-idle') {
        setIdle(msg.reason)
      } else if (msg.type === 'recording') {
        setRecording(msg.path)
      } else if (msg.type === 'rates') {
        setRates(msg)
      } else if (msg.type === 'frames') {
        setFrames(msg.state)
      }
    }
    ws.onclose = () => setIdle('Lost the connection to OpenWrtGUI. Open RF live again.')
    return () => {
      ws.onclose = null
      ws.close()
      socket.current = null
    }
  }, [id, radio])

  const station = chosen ?? latest?.stations[0]?.mac ?? Object.keys(lastSeen)[0] ?? null
  useEffect(() => {
    if (!station) return undefined
    const ask = (): void => socket.current?.send(JSON.stringify({ type: 'rates', mac: station }))
    ask()
    const timer = setInterval(ask, RATES_EVERY_MS)
    return () => clearInterval(timer)
  }, [station])

  const name = detail.data?.record.name ?? id
  const short = name.split(' · ')[0] || id
  const r = latest?.radio_sample
  const s = station ? lastSeen[station] : undefined
  const who = s?.name ?? station ?? 'the station'
  const hasLeft = Boolean(station && latest && !latest.stations.some((x) => x.mac === station) && lastSeen[station])
  const setting = wifi.data?.radios.find((x) => x.name === radio)?.txpower
  const series = station ? buffers[station] : undefined
  const now = latest ? Date.parse(latest.at) : 0 // charts are empty until the first sample
  const stations = Object.values(lastSeen)
  const record = (): void => {
    socket.current?.send(JSON.stringify({ type: 'record', on: !recording }))
    if (recording) setRecording(null)
  }

  return (
    <main className="wrap">
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <div>
          <div className="eyebrow">
            <span className="mono">{detail.data?.record.host ?? ''}</span> · {radio}
            {latest ? ` · ${latest.ifname}` : ''}
          </div>
          <div className="hrow">
            <h1>RF live</h1>
            <Help topic={HELP.rf} />
          </div>
        </div>
        <div className="spacer" />
        <button className="btn" type="button" aria-pressed={paused} onClick={() => setPaused(!paused)}>
          {paused ? 'Resume' : 'Pause'}
        </button>
        <div className="hrow">
          <HelpTip topic={HELP.rfRecord}>
            <button className="btn pri" type="button" onClick={record}>
              {recording ? 'Stop recording' : 'Record to CSV'}
            </button>
          </HelpTip>
          <Help topic={HELP.rfRecord} />
        </div>
      </div>
      <RouterSections routerId={id} name={name} current="rf" />
      {recording && <div className="note">Recording to {recording}</div>}
      {idle && (
        <div className="note w" role="status">
          {idle}
        </div>
      )}
      <div className="hrow">
        <h2>Radio</h2>
        <Help topic={HELP.rfRadio} />
      </div>
      <div className="rf-tiles">
        <Tile label="Channel" value={r?.channel != null ? `${r.channel} · ${r.width_mhz === 40 ? 'HT40' : 'HT20'}` : '—'} note={r?.freq_mhz ? `${r.freq_mhz} MHz` : ''} />
        <Tile
          label="TX power"
          value={r?.txpower_dbm != null ? `${r.txpower_dbm.toFixed(0)} dBm` : '—'}
          note={`set: ${setting?.kind === 'fixed' ? `fixed ${setting.dbm}` : 'auto'} · actual ${fmt(r?.txpower_dbm, 2)}`}
        />
        <Tile label="Air busy" value={r?.busy_pct != null ? `${r.busy_pct.toFixed(0)} %` : '—'} note="share of time the radio heard something">
          <div className="bar" role="img" aria-label={`Channel busy ${r?.busy_pct?.toFixed(0) ?? 'unknown'} percent`}>
            <span style={{ width: `${r?.busy_pct ?? 0}%` }} />
          </div>
        </Tile>
        <Tile label="Noise floor" value={r?.noise_dbm != null ? dbm(r.noise_dbm) : 'not reported'} note={r?.noise_dbm != null ? 'from the channel survey' : 'this driver gives no noise value'} />
        <Tile label="ACK failures" value={r?.ack_fail_per_s != null ? `${fmt(r.ack_fail_per_s, 0)} /s` : '—'} note="dot11ACKFailureCount change per second" />
      </div>
      <div className="row">
        <div className="seg" role="group" aria-label="Station">
          {stations.map((x) => (
            <button key={x.mac} type="button" className={x.mac === station ? 'on' : ''} aria-pressed={x.mac === station} onClick={() => setChosen(x.mac)}>
              {x.name ? `${x.name} · ${x.mac}` : x.mac}
            </button>
          ))}
        </div>
        {hasLeft && <span className="b park">{who} left</span>}
        <div className="spacer" />
        <div className="seg" role="group" aria-label="Window">
          {WINDOWS.map(([w, label]) => (
            <button key={w} type="button" className={windowS === w ? 'on' : ''} aria-pressed={windowS === w} onClick={() => setWindowS(w)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      {!s ? (
        <div className="muted">{latest ? 'No station is connected to this radio.' : 'Waiting for the first sample…'}</div>
      ) : (
        <div className="rf-cols">
          <section className="card stack" aria-label="RX at AP · station → AP">
            <div className="hrow">
              <span className="swatch" style={{ background: 'var(--rx)' }} />
              <h2>RX at AP</h2>
              <span className="muted">station → AP</span>
              <Help topic={HELP.rfRx} />
            </div>
            <Kv
              rows={[
                ['Signal', `${s.signal_dbm != null ? dbm(s.signal_dbm) : '—'}${s.signal_avg_dbm != null ? ` · avg ${dbm(s.signal_avg_dbm)}` : ''}`],
                ['Per antenna', s.chains.length > 0 ? s.chains.map((c) => dbm(c)).join(' / ') : '—'],
                ['RX rate', `${rateText(s.rx)} ${rateDetail(s.rx)}`.trim()],
                ['RX packets', `${fmt(s.rx_pps, 0)} /s · ${fmt(s.rx_kbps != null ? s.rx_kbps / 8 : null, 0)} kB/s`],
                ['RX drops', s.rx_drops != null ? String(s.rx_drops) : '—'],
                ['Last frame', s.inactive_ms != null ? `${s.inactive_ms} ms ago` : '—'],
              ]}
            />
            <RfChart title={`Signal from ${who}`} unit="dBm" series={[{ label: 'Signal', tone: 'rx', points: windowed(series?.signal ?? [], now, windowS) }]} />
          </section>
          <section className="card stack" aria-label="TX from AP · AP → station">
            <div className="hrow">
              <span className="swatch" style={{ background: 'var(--tx)' }} />
              <h2>TX from AP</h2>
              <span className="muted">AP → station</span>
              <Help topic={HELP.rfTx} />
            </div>
            <Kv
              rows={[
                ['TX rate', `${rateText(s.tx)} ${rateDetail(s.tx)}`.trim()],
                ['Retries', s.retry_pct != null ? `${s.retry_pct.toFixed(1)} % of frames` : '—'],
                ['Failed', s.failed_per_s != null ? `${s.failed_per_s.toFixed(1)} /s` : '—'],
                ['Expected throughput', s.expected_mbps != null ? `${s.expected_mbps.toFixed(0)} Mb/s` : '—'],
                ['TX packets', `${fmt(s.tx_pps, 0)} /s · ${fmt(s.tx_kbps != null ? s.tx_kbps / 8 : null, 0)} kB/s`],
                ['ACK signal', s.ack_signal_dbm != null ? dbm(s.ack_signal_dbm) : 'not reported by this driver'],
              ]}
            />
            <div className="hrow">
              <h3 style={{ fontSize: 13 }}>Charts</h3>
              <Help topic={HELP.rfCharts} />
            </div>
            <RfChart
              title="Data rate"
              unit="Mb/s"
              series={[
                { label: 'TX from AP', tone: 'tx', points: windowed(series?.tx ?? [], now, windowS) },
                { label: 'RX at AP', tone: 'rx', points: windowed(series?.rx ?? [], now, windowS) },
              ]}
            />
          </section>
        </div>
      )}
      <section className="card stack" aria-labelledby="rates-h">
        <div className="hrow">
          <h2 id="rates-h">Which rates reach {who}</h2>
          <Help topic={HELP.rfRates} />
        </div>
        <span className="muted">AP → station, from the router's rate control (minstrel). Success = frames the station acknowledged.</span>
        <RatesTable rows={rates?.mac === station ? rates.rows : undefined} error={rates?.mac === station ? rates.error : undefined} />
      </section>
      <FrameAnalysis routerId={id} radio={radio} live={frames} retryPct={s?.retry_pct ?? null} />
      <ChannelAnalysis routerId={id} radio={radio} />
      <span className="sr-only">{short}</span>
    </main>
  )
}
