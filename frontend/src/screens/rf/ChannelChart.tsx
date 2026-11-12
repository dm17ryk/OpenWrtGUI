import type { Bss, ScanResult } from '../../api/types'

export const STEP = 12 // svg units per 5 MHz (one channel spacing)
const BUSY_H = 48
const NET_H = 96
const AXIS_H = 18

/** A BSS's occupied band: the primary channel's frequency, ±10 MHz for 40 MHz (secondary above or below). */
function band(b: Bss): [number, number] {
  const centre = b.freq_mhz + (b.secondary === 'above' ? 10 : b.secondary === 'below' ? -10 : 0)
  return [centre - b.width_mhz / 2, centre + b.width_mhz / 2]
}

/** How strong, 0..1, from -100 dBm (nothing) to -20 dBm (next to the antenna). */
const strength = (dbm: number | null): number => (dbm === null ? 0.1 : Math.min(1, Math.max(0.05, (dbm + 100) / 80)))

/** LuCI's channel analysis picture: each network's span over the channels by signal, and each channel's busy share. */
export function ChannelChart({ result }: { result: ScanResult }) {
  const channels = result.channels
  if (channels.length === 0) return null
  const lo = channels[0].freq_mhz - 10
  const hi = channels[channels.length - 1].freq_mhz + 10
  const x = (f: number): number => ((f - lo) / 5) * STEP
  const width = x(hi)
  const height = NET_H + BUSY_H + AXIS_H
  return (
    <div className="scroll-x">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        style={{ maxWidth: width * 3, minWidth: 280 }}
        role="img"
        aria-label={`${channels.length} channels, ${result.networks.length} networks heard`}
      >
        {result.networks.map((b) => {
          const [from, to] = band(b)
          const h = strength(b.signal_dbm) * NET_H
          return (
            <rect
              key={b.bssid}
              data-testid={`span-${b.bssid}`}
              x={x(from)}
              y={NET_H - h}
              width={x(to) - x(from)}
              height={h}
              rx={STEP}
              fill={b.own ? 'var(--tx)' : 'var(--rx)'}
              fillOpacity={0.18}
              stroke={b.own ? 'var(--tx)' : 'var(--rx)'}
            >
              <title>{`${b.ssid ?? '(hidden)'} · channel ${b.channel ?? '?'} · ${b.signal_dbm ?? '?'} dBm`}</title>
            </rect>
          )
        })}
        {channels.map((c) => {
          const h = ((c.busy_pct ?? 0) / 100) * BUSY_H
          return (
            <g key={c.channel}>
              <rect x={x(c.freq_mhz) - STEP / 3} y={NET_H + BUSY_H - h} width={(2 * STEP) / 3} height={h} fill="var(--muted)">
                <title>{`Channel ${c.channel}: ${c.busy_pct === null ? 'not visited' : `${c.busy_pct.toFixed(1)} % busy`}`}</title>
              </rect>
              <text x={x(c.freq_mhz)} y={height - 4} textAnchor="middle" fontSize={9} fill="var(--muted)">
                {c.channel}
              </text>
            </g>
          )
        })}
        <line x1={0} x2={width} y1={NET_H} y2={NET_H} stroke="var(--axis)" />
      </svg>
    </div>
  )
}
