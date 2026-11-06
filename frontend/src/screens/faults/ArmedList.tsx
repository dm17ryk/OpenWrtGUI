import type { ArmedFault } from '../../api/types'
import { untilText } from './faults'

type Props = { armed: readonly ArmedFault[]; now: Date; onClear: (ids: string[]) => void }

/** What this app has armed on the router, read from its records in /tmp/owg, so it survives an app restart. */
export function ArmedList({ armed, now, onClear }: Props) {
  if (armed.length === 0) return null
  return (
    <div className="scroll-x">
      <table className="tbl" aria-label="Armed faults">
        <thead>
          <tr>
            <th>Fault</th>
            <th>Target</th>
            <th>Device</th>
            <th>Ends</th>
            <th>
              <span className="sr-only">Clear</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {armed.map((f) => (
            <tr key={f.id}>
              <td>{f.summary}</td>
              <td className="mono">{[f.target.name, f.target.ip, f.target.mac].filter(Boolean).join(' · ')}</td>
              <td className="mono">{f.device ?? '—'}</td>
              <td>{untilText(f.until, now)}</td>
              <td>
                <button className="btn" type="button" onClick={() => onClear([f.id])}>
                  Clear
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
