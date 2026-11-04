import type { RadioStatus, RouterItem } from '../api/types'
import { Help } from '../help/Help'
import { HELP } from '../help/topics'
import { radioText } from './routerState'

const BANDS: ReadonlyArray<{ id: string; label: string; channels: number[] }> = [
  { id: '2g', label: '2.4 GHz air', channels: Array.from({ length: 13 }, (_, i) => i + 1) },
  { id: '5g', label: '5 GHz air', channels: [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 149, 153, 157, 161, 165] },
  { id: '6g', label: '6 GHz air', channels: Array.from({ length: 30 }, (_, i) => 1 + i * 8) },
]

function span(radio: RadioStatus, count: number, channels: number[]): { start: number; end: number } {
  const index = Math.max(0, channels.indexOf(Number(radio.channel)))
  const width = radio.htmode?.includes('40') ? 7 : 3
  const half = Math.floor(width / 2)
  const start = radio.htmode?.includes('40') ? index : Math.max(0, index - half)
  return { start: start + 1, end: Math.min(count, start + width) + 1 }
}

export function AirMap({ items }: { items: RouterItem[] }) {
  const withRadios = items.filter((i) => i.status && i.status.radios.length > 0)
  return (
    <>
      {BANDS.map((band) => {
        const rows = withRadios.flatMap((item) =>
          (item.status?.radios ?? []).filter((r) => r.band === band.id).map((r) => ({ item, radio: r })),
        )
        if (rows.length === 0) return null
        const cols = `repeat(${band.channels.length}, minmax(0, 1fr))`
        return (
          <section className="card stack" key={band.id} aria-labelledby={`air-${band.id}`}>
            <div className="row">
              <div className="hrow">
                <h2 id={`air-${band.id}`}>{band.label}</h2>
                <Help topic={HELP.airMap} />
              </div>
              <span className="b air">on air</span>
              <span className="b park">parked (staged channel)</span>
            </div>
            <div className="scroll-x">
              <div style={{ minWidth: 560, display: 'grid', gridTemplateColumns: '130px minmax(0, 1fr)', gap: '10px 14px', alignItems: 'center' }}>
                <div />
                <div className="mono" style={{ display: 'grid', gridTemplateColumns: cols, fontSize: 11, color: 'var(--muted)', textAlign: 'center' }}>
                  {band.channels.map((c) => (
                    <div key={c}>{c}</div>
                  ))}
                </div>
                {rows.map(({ item, radio }) => {
                  const { start, end } = span(radio, band.channels.length, band.channels)
                  return [
                    <div key={`${item.record.id}-${radio.name}-n`} style={{ fontWeight: 600, fontSize: 13 }}>
                      {item.record.name.split(' · ')[0]}{' '}
                      <span className="mono" style={{ fontWeight: 400, color: 'var(--muted)' }}>
                        .{item.record.host.split('.').slice(-2).join('.')}
                      </span>
                    </div>,
                    <div key={`${item.record.id}-${radio.name}-s`} style={{ display: 'grid', gridTemplateColumns: cols, background: 'var(--surface2)', borderRadius: 6, minHeight: 30 }}>
                      <div
                        className="mono"
                        title={radioText(radio)}
                        style={{
                          gridColumn: `${start} / ${end}`,
                          borderRadius: 6,
                          padding: '6px 8px',
                          fontSize: 12,
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          background: radio.up ? 'var(--ok-soft)' : 'transparent',
                          color: radio.up ? 'var(--ok)' : 'var(--warn)',
                          border: radio.up ? '1px solid var(--ok)' : '1px dashed var(--warn)',
                        }}
                      >
                        {radioText(radio)}
                      </div>
                    </div>,
                  ]
                })}
              </div>
            </div>
          </section>
        )
      })}
    </>
  )
}
