import { Link } from 'react-router'
import type { CapabilityRow } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { capabilityLink } from './capabilityLinks'

const STYLE: Record<CapabilityRow['state'], string> = {
  'in image': 'air',
  'added after flashing': 'neu',
  missing: 'missing',
}

function chipText(row: CapabilityRow): string {
  const state = row.state === 'missing' && row.reason ? `missing: ${row.reason}` : row.state
  return `${row.name} · ${state}`
}

/**
 * Capabilities (spec 7.8 Phase 2): what this router can do, from its image and what was added after flashing.
 * A chip opens the screen that uses the capability; a missing one still opens it, and that screen says what it
 * needs. The state is in the words, never only in the colour.
 */
export function CapabilityChips({ routerId, rows }: { routerId: string; rows: readonly CapabilityRow[] }) {
  return (
    <section className="card stack" aria-labelledby="caps-h">
      <div className="hrow">
        <h2 id="caps-h">Capabilities</h2>
        <Help topic={HELP.discoveryCapabilities} />
      </div>
      <ul className="chips">
        {rows.map((row) => {
          const to = capabilityLink(routerId, row.name)
          const className = `b chip ${STYLE[row.state]}`
          return (
            <li key={row.name}>
              {to ? (
                <Link to={to} className={className}>
                  {chipText(row)}
                </Link>
              ) : (
                <span className={className}>{chipText(row)}</span>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
