import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { ApiError, apiFetch } from '../../api/client'
import type { FirewallState, IptablesPresence, RouterDetail } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { RouterSections } from '../../shell/RouterSections'
import { luciPageLink } from '../luci/pages'
import { shortName } from '../net/rows'
import { CustomTab } from './CustomTab'
import { IptablesTab } from './IptablesTab'
import { ModelCard } from './ModelCard'
import { RawTab } from './RawTab'
import { SectionTab } from './SectionTab'
import type { Kind } from './sections'
import { TablesTab } from './TablesTab'
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
  ['iptables', 'Legacy iptables'], // v1.0a2 D6: shown when the router has iptables, fw4 or not
] as const
type Tab = (typeof TABS)[number][0]
const SECTION_TABS: Partial<Record<Tab, Kind>> = { rules: 'rule', forwards: 'redirect', nat: 'nat', ipsets: 'ipset' }
// tabs whose tables show live packet counters
const LIVE: readonly Tab[] = ['rules', 'forwards', 'nat']

/** Firewall (spec 7.6): the filtering model, zones, and fw4's other sections and nftables tables, as tabs. */
export function FirewallScreen() {
  const { id = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const client = useQueryClient()
  const detail = useQuery({ queryKey: ['router', id], queryFn: () => apiFetch<RouterDetail>(`/api/routers/${id}`) })
  const asked = params.get('tab')
  const legacy = useQuery({
    queryKey: ['firewall-iptables-present', id],
    queryFn: () => apiFetch<IptablesPresence>(`/api/routers/${id}/firewall/iptables/present`),
  })
  const askedTab = TABS.find(([key]) => key === asked)?.[0]
  const fw = useQuery({
    queryKey: ['firewall', id],
    queryFn: () => apiFetch<FirewallState>(`/api/routers/${id}/firewall`),
    refetchInterval: askedTab && LIVE.includes(askedTab) ? 5000 : false,
  })
  // on a router this screen does not manage (fw3), Legacy iptables is the only tab (v1.0a2 D6)
  const tab: Tab = askedTab ?? (fw.data && !fw.data.available && legacy.data?.iptables ? 'iptables' : 'zones')
  const shown = TABS.filter(([key]) => (key === 'iptables' ? Boolean(legacy.data?.iptables) : Boolean(fw.data?.available)))
  // Unlocked tables stay unlocked until Lock or until the user leaves this router.
  const [unlocked, setUnlocked] = useState<{ router: string; keys: string[] }>({ router: id, keys: [] })
  const keys = unlocked.router === id ? unlocked.keys : []
  const name = detail.data?.record.name ?? id
  const pick = (key: Tab): void => setParams(key === 'zones' ? {} : { tab: key }, { replace: true })
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
        {state?.available && <span className="b neu mono">nftables · fw4</span>}
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
      {shown.length > 0 && (
        <div className="tabs" role="tablist" aria-label="Firewall views">
          {shown.map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              className={`tab${key === tab ? ' on' : ''}`}
              aria-selected={key === tab}
              onClick={() => pick(key)}
            >
              {label}
            </button>
          ))}
        </div>
      )}
      {tab === 'iptables' && legacy.data?.iptables && <IptablesTab routerId={id} short={cards.short} />}
      {tab === 'iptables' && legacy.data && !legacy.data.iptables && (
        <div className="note">No iptables on this router: fw4&apos;s rules are under Raw ruleset.</div>
      )}
      {state?.available && (
        <>
          {tab === 'zones' && (
            <>
              <ModelCard {...cards} routerName={name} state={state} />
              <ZonesTab {...cards} state={state} />
            </>
          )}
          {SECTION_TABS[tab] && <SectionTab key={tab} kind={SECTION_TABS[tab]} {...cards} state={state} />}
          {tab === 'custom' && <CustomTab {...cards} state={state} />}
          {tab === 'tables' && (
            <TablesTab
              {...cards}
              state={state}
              unlocked={keys}
              onUnlock={(key) => setUnlocked({ router: id, keys: [...keys, key] })}
              onLock={(key) => setUnlocked({ router: id, keys: keys.filter((k) => k !== key) })}
              onZones={() => pick('zones')}
            />
          )}
          {tab === 'raw' && <RawTab routerId={id} />}
        </>
      )}
    </main>
  )
}
