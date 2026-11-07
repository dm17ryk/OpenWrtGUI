import { Link } from 'react-router'
import { luciPageLink, useLuciPages } from '../screens/luci/pages'

export type Section = 'overview' | 'wifi' | 'rf' | 'network' | 'ports' | 'firewall' | 'faults' | 'luci'

type Props = { routerId: string; name: string; current: Section; luciPath?: string }

/**
 * The router's own screens, then the LuCI pages that have no screen here yet. A router can have forty of those,
 * so they fold into one list; the one open now stays visible on its own.
 */
export function RouterSections({ routerId, name, current, luciPath }: Props) {
  const pages = useLuciPages(routerId)
  const base = `/routers/${routerId}`
  const own: ReadonlyArray<readonly [Section | 'terminal', string, string]> = [
    ['overview', 'Overview', base],
    ['wifi', 'Wi-Fi', `${base}/wifi`],
    ['rf', 'RF live', `${base}/rf`],
    ['network', 'Network & DHCP', `${base}/network`],
    ['ports', 'Ports & VLANs', `${base}/ports`],
    ['firewall', 'Firewall', `${base}/firewall`],
    ['faults', 'Faults & capture', `${base}/faults`],
    ['terminal', 'Terminal', `/terminal/${routerId}`],
  ]
  const fallback = (pages.data ?? []).filter((p) => p.native === null)
  const open = current === 'luci' ? fallback.find((p) => p.path === luciPath) : undefined
  const short = name.split(' · ')[0] || routerId
  return (
    <nav className="sections" aria-label={`${short} sections`}>
      {own.map(([key, label, to]) => (
        <Link key={key} to={to} aria-current={key === current ? 'page' : undefined}>
          {label}
        </Link>
      ))}
      {open && (
        <Link to={luciPageLink(routerId, open.path)} aria-current="page">
          LuCI: {open.label}
        </Link>
      )}
      {fallback.length > 0 && (
        <details className="sections-more">
          <summary>LuCI pages ({fallback.length})</summary>
          <div className="sections-menu">
            {fallback.map((p) => (
              <Link key={p.path} to={luciPageLink(routerId, p.path)}>
                {p.label}
              </Link>
            ))}
          </div>
        </details>
      )}
    </nav>
  )
}
