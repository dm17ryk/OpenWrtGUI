import { useEffect, useRef, useState } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { toUplot, type Point } from './series'

export type ChartSeries = { label: string; tone: 'rx' | 'tx'; points: Point[] }

/** `xRange` (seconds) pins the time axis to the window, so a chart with one or two points still reads as now. */
type Props = { title: string; unit: string; series: ChartSeries[]; xRange?: readonly [number, number] }

const HEIGHT = 210

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888888'
}

/** The theme the page shows now; the chart is rebuilt with that theme's colours when it changes. */
function useTheme(): string {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme ?? 'light')
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(document.documentElement.dataset.theme ?? 'light'))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])
  return theme
}

function columns(series: ChartSeries[]): uPlot.AlignedData {
  const [x] = toUplot(series[0]?.points ?? [])
  return [x, ...series.map((s) => toUplot(s.points)[1])]
}

/** A line chart for RF values: 2 px lines in the RX / TX colours, a hover readout in the legend. */
export function RfChart({ title, unit, series, xRange }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const plot = useRef<uPlot | null>(null)
  const range = useRef(xRange)
  const theme = useTheme()
  const labels = series.map((s) => `${s.label}:${s.tone}`).join('|')
  const pinned = xRange !== undefined

  useEffect(() => {
    const el = box.current
    if (!el) return undefined
    const axis = token('--axis')
    const grid = token('--grid')
    const ink = token('--muted')
    const opts: uPlot.Options = {
      width: el.clientWidth || 600,
      height: HEIGHT,
      scales: {
        x: pinned ? { time: true, range: (_u, min, max) => (range.current ? [range.current[0], range.current[1]] : [min, max]) } : { time: true },
      },
      axes: [
        { stroke: ink, grid: { stroke: grid, width: 1 }, ticks: { stroke: axis, width: 1 } },
        { stroke: ink, grid: { stroke: grid, width: 1 }, ticks: { stroke: axis, width: 1 }, label: unit, size: 56 },
      ],
      // a line needs two points: until then the sample shows as a dot
      series: [{}, ...series.map((s) => ({ label: s.label, stroke: token(`--${s.tone}`), width: 2, points: { show: (u: uPlot) => u.data[0].length < 2, size: 7 } }))],
      cursor: { drag: { x: false, y: false } },
      legend: { show: true, live: true },
    }
    plot.current = new uPlot(opts, columns(series), el)
    const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => plot.current?.setSize({ width: el.clientWidth, height: HEIGHT }))
    resize?.observe(el)
    return () => {
      resize?.disconnect()
      plot.current?.destroy()
      plot.current = null
    }
    // the chart is rebuilt only when its series or the theme change; data changes go through setData
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [labels, unit, theme, pinned])

  useEffect(() => {
    range.current = xRange
    plot.current?.setData(columns(series))
  }, [series, xRange])

  const last = series.map((s) => [s.label, s.points.at(-1)?.v ?? null] as const)
  return (
    <figure className="rf-chart" aria-label={title}>
      <figcaption className="row">
        <strong>{title}</strong>
        <span className="muted">{unit}</span>
      </figcaption>
      <div ref={box} />
      <table className="sr-only">
        <caption>{title}, latest values</caption>
        <tbody>
          {last.map(([label, v]) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              <td>{v ?? 'no value'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  )
}
