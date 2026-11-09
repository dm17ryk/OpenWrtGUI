import { useQuery } from '@tanstack/react-query'
import { useParams, useSearchParams } from 'react-router'
import { ApiError, apiFetch } from '../../api/client'
import type { RouterDetail, SystemOverview } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { RouterSections } from '../../shell/RouterSections'
import { StatusTab } from './StatusTab'

const TABS = [['status', 'Status']] as const
type Tab = (typeof TABS)[number][0]

/** System (spec 7.11): the router's own state and system settings, one tab per LuCI page it replaces (D1). */
export function SystemScreen() {
  const { id = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const detail = useQuery({ queryKey: ['router', id], queryFn: () => apiFetch<RouterDetail>(`/api/routers/${id}`) })
  const overview = useQuery({ queryKey: ['system', id], queryFn: () => apiFetch<SystemOverview>(`/api/routers/${id}/system`) })
  const asked = params.get('tab')
  const tab: Tab = TABS.find(([key]) => key === asked)?.[0] ?? 'status'
  const name = detail.data?.record.name ?? id
  const pick = (key: Tab): void => setParams(key === 'status' ? {} : { tab: key }, { replace: true })
  return (
    <main className="wrap">
      <div>
        <div className="eyebrow">
          <span className="mono">{detail.data?.record.host ?? ''}</span>
          {overview.data?.model ? ` · ${overview.data.model}` : ''}
        </div>
        <div className="hrow">
          <h1>System</h1>
          <Help topic={HELP.system} />
        </div>
      </div>
      <RouterSections routerId={id} name={name} current="system" />
      <div className="tabs" role="tablist" aria-label="System views">
        {TABS.map(([key, label]) => (
          <button key={key} type="button" role="tab" className={`tab${key === tab ? ' on' : ''}`} aria-selected={key === tab} onClick={() => pick(key)}>
            {label}
          </button>
        ))}
      </div>
      {tab === 'status' && (
        <>
          {overview.isPending && <div className="muted">Reading the router…</div>}
          {overview.error && <div className="note x">{overview.error instanceof ApiError ? overview.error.detail : overview.error.message}</div>}
          {overview.data && <StatusTab routerId={id} overview={overview.data} />}
        </>
      )}
    </main>
  )
}
