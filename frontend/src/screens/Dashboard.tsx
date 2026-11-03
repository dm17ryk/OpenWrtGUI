import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '../api/client'
import type { RouterItem } from '../api/types'
import { RouterRail } from '../shell/RouterRail'
import { AirMap } from './AirMap'
import { Attention } from './Attention'
import { RouterCard } from './RouterCard'
import { plural, stationCount } from './routerState'

export function Dashboard() {
  const routers = useQuery({ queryKey: ['routers'], queryFn: () => apiFetch<RouterItem[]>('/api/routers') })
  const items = routers.data ?? []
  const onAir = items.reduce((n, i) => n + (i.status?.radios.filter((r) => r.up).length ?? 0), 0)
  const stations = items.reduce((n, i) => n + stationCount(i.status), 0)
  return (
    <div className="wrap">
      <div className="shell">
        <RouterRail items={items} />
        <main className="main">
          <div className="row" style={{ alignItems: 'flex-end' }}>
            <div>
              <div className="eyebrow">Bench</div>
              <h1>
                {plural(items.length, 'router')} · {onAir} {onAir === 1 ? 'radio' : 'radios'} on air ·{' '}
                {plural(stations, 'station')}
              </h1>
            </div>
            <div className="spacer" />
            <span className="muted">Refreshed every 5 s over SSH</span>
          </div>
          {routers.isError && <div className="note x">Could not load the routers: {String(routers.error)}</div>}
          {items.length === 0 && routers.isSuccess && (
            <div className="note">No routers yet. Use Add router to connect the first one.</div>
          )}
          <AirMap items={items} />
          <div className="cards">
            {items.map((item) => (
              <RouterCard key={item.record.id} item={item} />
            ))}
          </div>
          <Attention items={items} />
        </main>
      </div>
    </div>
  )
}
