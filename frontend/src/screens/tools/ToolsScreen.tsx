import { useQuery } from '@tanstack/react-query'
import { Navigate, useNavigate, useParams } from 'react-router'
import { apiFetch } from '../../api/client'
import type { RouterDetail } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { RouterSections } from '../../shell/RouterSections'
import { ConnectionsTab } from './ConnectionsTab'
import { PortStatsTab } from './PortStatsTab'
import { ThroughputTab } from './ThroughputTab'
import { TOOL_PAGES, toolPage } from './toolPages'
import { TrafficTab } from './TrafficTab'

/**
 * Tools (spec 7.8 Phase 2, v1.2a R2): one tab per tool page; Discovery's capability chips open them. A page
 * whose capability the router lacks still opens and says what it needs.
 */
export function ToolsScreen() {
  const { id = '', tool } = useParams()
  const navigate = useNavigate()
  const detail = useQuery({ queryKey: ['router', id], queryFn: () => apiFetch<RouterDetail>(`/api/routers/${id}`) })
  if (tool === undefined) return <Navigate to={`/routers/${id}/tools/${TOOL_PAGES[0].key}`} replace />
  const page = toolPage(tool)
  const name = detail.data?.record.name ?? id
  return (
    <main className="wrap">
      <div>
        <div className="eyebrow">
          <span className="mono">{detail.data?.record.host ?? ''}</span>
        </div>
        <div className="hrow">
          <h1>Tools</h1>
          <Help topic={HELP.tools} />
        </div>
      </div>
      <RouterSections routerId={id} name={name} current="tools" />
      <div className="tabs" role="tablist" aria-label="Tool pages">
        {TOOL_PAGES.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            role="tab"
            className={`tab${key === page ? ' on' : ''}`}
            aria-selected={key === page}
            onClick={() => void navigate(`/routers/${id}/tools/${key}`)}
          >
            {label}
          </button>
        ))}
      </div>
      {page === null && <div className="note x">No tool page called {tool}.</div>}
      {page === 'port-stats' && <PortStatsTab routerId={id} />}
      {page === 'connections' && <ConnectionsTab routerId={id} />}
      {page === 'throughput' && <ThroughputTab routerId={id} />}
      {page === 'traffic' && <TrafficTab routerId={id} />}
    </main>
  )
}
