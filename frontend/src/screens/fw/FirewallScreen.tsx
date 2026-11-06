import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams, useSearchParams } from 'react-router'
import { ApiError, apiFetch } from '../../api/client'
import type { FirewallState, RouterDetail } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { RouterSections } from '../../shell/RouterSections'
import { luciPageLink } from '../luci/pages'
import { shortName } from '../net/rows'
import { ModelCard } from './ModelCard'
import { ZonesTab } from './ZonesTab'

const TABS = [
  ['zones', 'Zones and model'],
  ['rules', 'Traffic rules'],
  ['forwards', 'Port forwards'],
  ['nat', 'NAT rules'],
  ['ipsets', 'IP sets'],
  ['custom', 'Custom rules'],
  ['tables', 'All nftables tables'],
  ['raw', 'Raw ruleset'],
] as const
type Tab = (typeof TABS)[number][0]

/** Firewall (spec 7.6): the filtering model, zones, and fw4's other sections and nftables tables, as tabs. */
export function FirewallScreen() {
  const { id = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const client = useQueryClient()
  const detail = useQuery({ queryKey: ['router', id], queryFn: () => apiFetch<RouterDetail>(`/api/routers/${id}`) })
  const fw = useQuery({ queryKey: ['firewall', id], queryFn: () => apiFetch<FirewallState>(`/api/routers/${id}/firewall`) })
  const name = detail.data?.record.name ?? id
  const asked = params.get('tab')
  const tab: Tab = TABS.find(([key]) => key === asked)?.[0] ?? 'zones'
  const refresh = (): void => {
    void client.invalidateQueries({ queryKey: ['firewall', id] })
    void client.invalidateQueries({ queryKey: ['firewall-ruleset', id] })
    void client.invalidateQueries({ queryKey: ['router', id] })
  }
  const cards = { routerId: id, short: shortName(name, id), onApplied: refresh }
  const state = fw.data
  return (
    <main className="wrap">
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <div>
          <div className="eyebrow">
            <span className="mono">{detail.data?.record.host ?? ''}</span>
            {detail.data?.summary ? ` · ${detail.data.summary.model}` : ''}
          </div>
          <div className="hrow">
            <h1>Firewall</h1>
            <Help topic={HELP.firewall} />
          </div>
        </div>
        <span className="spacer" />
        <span className="b neu mono">nftables · fw4</span>
      </div>
      <RouterSections routerId={id} name={name} current="firewall" />
      {fw.isError && <div className="note x">{fw.error instanceof ApiError ? fw.error.detail : String(fw.error)}</div>}
      {state && !state.available && (
        <div className="note w row">
          <span>{state.reason}</span>
          <Link className="btn" to={luciPageLink(id, 'admin/network/firewall/zones')}>
            Open LuCI&apos;s firewall
          </Link>
        </div>
      )}
      {state?.available && (
        <>
          <div className="tabs" role="tablist" aria-label="Firewall views">
            {TABS.map(([key, label]) => (
              <button
                key={key}
                type="button"
                role="tab"
                className={`tab${key === tab ? ' on' : ''}`}
                aria-selected={key === tab}
                onClick={() => setParams(key === 'zones' ? {} : { tab: key }, { replace: true })}
              >
                {label}
              </button>
            ))}
          </div>
          {tab === 'zones' && (
            <>
              <ModelCard {...cards} routerName={name} state={state} />
              <ZonesTab {...cards} state={state} />
            </>
          )}
        </>
      )}
    </main>
  )
}
