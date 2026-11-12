import type { StepResult } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { MODE_LABEL } from './draft'

function proof(r: StepResult): string {
  if (r.proven) return 'proven'
  const failed = r.checks.filter((c) => c.ok === false).map((c) => `${c.name}: ${c.detail}`)
  return failed.join('; ') || 'not proven'
}

function rejoin(r: StepResult): string {
  if (r.rejoined === null) return '–'
  return r.rejoined && r.rejoin_s !== null ? `${r.rejoin_s.toFixed(0)} s` : 'not re-joined'
}

/** One row per step (plan D10): what was proven, the beacon rate, and the station's re-join time. */
export function StepResults({ results, csvPath }: { results: StepResult[]; csvPath: string | null }) {
  if (results.length === 0) return null
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="hrow">
        <div className="eyebrow">Results</div>
        <Help topic={HELP.wifiStepResults} />
      </div>
      <div className="scroll-x">
        <table className="tbl" aria-label="Step-through results">
          <thead>
            <tr>
              <th>Step</th>
              <th>Mode</th>
              <th>Channel</th>
              <th>TX power</th>
              <th>Proof on air</th>
              <th>Beacon</th>
              <th>Re-join</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <tr key={r.index}>
                <td className="mono">{r.index}</td>
                <td>{MODE_LABEL[r.mode]}</td>
                <td className="mono">{r.channel}</td>
                <td className="mono">{r.txpower_dbm === null ? 'as it was' : `${r.txpower_dbm} dBm`}</td>
                <td className={r.proven ? '' : 'bad'}>{proof(r)}</td>
                <td className="mono">{r.beacon ?? '–'}</td>
                <td className="mono">{rejoin(r)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {csvPath && <div className="muted mono">Saved to {csvPath}</div>}
    </div>
  )
}
