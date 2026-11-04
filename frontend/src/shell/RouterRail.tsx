import { NavLink } from 'react-router'
import type { RouterItem } from '../api/types'
import { Help, HelpTip } from '../help/Help'
import { HELP } from '../help/topics'
import { radioLine, routerState } from '../screens/routerState'

const DOT: Record<ReturnType<typeof routerState>, string> = {
  'on air': 'var(--ok)',
  parked: 'var(--warn)',
  unreachable: 'var(--bad)',
  'needs app key': 'var(--muted)',
  connecting: 'var(--muted)',
}

export function RouterRail({ items }: { items: RouterItem[] }) {
  return (
    <aside className="rail" aria-label="Routers">
      <div className="hrow" style={{ padding: '0 12px 4px' }}>
        <span className="eyebrow">Routers</span>
        <Help topic={HELP.routerList} />
      </div>
      {items.map((item) => {
        const state = routerState(item)
        return (
          <NavLink key={item.record.id} to={`/routers/${item.record.id}`} className={({ isActive }) => (isActive ? 'rt active' : 'rt')}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600 }}>
              <span className="dot" style={{ background: DOT[state] }} />
              {item.record.name}
            </span>
            <span className="mono" style={{ fontSize: 12, color: 'var(--muted)' }}>
              {item.record.host}
              {item.status ? ` · ${radioLine(item.status)}` : ''}
            </span>
          </NavLink>
        )
      })}
      <div style={{ padding: '12px 0 20px' }}>
        <HelpTip topic={HELP.addRouter}>
          <NavLink className="btn" to="/add">
            + Add router
          </NavLink>
        </HelpTip>
      </div>
    </aside>
  )
}
