import type { RateRow } from '../../api/types'

type Props = { rows: RateRow[] | undefined; error: string | undefined }

/** AP → station rates from minstrel: tries, acknowledged share, and the rate in use. */
export function RatesTable({ rows, error }: Props) {
  if (error) return <div className="muted">{error}</div>
  if (!rows) return <div className="muted">Reading the router's rate statistics…</div>
  if (rows.length === 0) return <div className="muted">No rate statistics for this station yet.</div>
  return (
    <div className="scroll-x">
      <table className="tbl" aria-label="Rates">
        <thead>
          <tr>
            <th>Rate</th>
            <th>Mode</th>
            <th>Attempts</th>
            <th>Success</th>
            <th aria-hidden="true" />
            <th>
              <span className="sr-only">In use</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.mode}-${r.rate}`}>
              <td className="mono">{r.rate}</td>
              <td>{r.mode}</td>
              <td className="mono">{r.attempts}</td>
              <td className="mono">{r.success_pct.toFixed(0)} %</td>
              <td style={{ width: '40%' }} aria-hidden="true">
                <div className="bar">
                  <span style={{ width: `${Math.max(0, Math.min(100, r.success_pct))}%` }} />
                </div>
              </td>
              <td>{r.in_use && <span className="b air">in use</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
