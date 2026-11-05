import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { apiFetch } from '../api/client'

export type Section = 'overview' | 'wifi' | 'rf' | 'luci'

export type LuciPageLink = { path: string; title: string; native: string | null }

type Props = { routerId: string; name: string; current: Section; luciPath?: string }

/** The router's own screens, then every LuCI page that has no screen here yet. */
export function RouterSections({ routerId, name, current, luciPath }: Props) {
  const pages = useQuery({
    queryKey: ['luci-pages', routerId],
    queryFn: () => apiFetch<LuciPageLink[]>(`/api/routers/${routerId}/luci/pages`),
    retry: false,
    staleTime: 60_000,
  })
  const base = `/routers/${routerId}`
  const own: ReadonlyArray<readonly [Section | 'terminal', string, string]> = [
    ['overview', 'Overview', base],
    ['wifi', 'Wi-Fi', `${base}/wifi`],
    ['rf', 'RF live', `${base}/rf`],
    ['terminal', 'Terminal', `/terminal/${routerId}`],
  ]
  const fallback = (pages.data ?? []).filter((p) => p.native === null)
  const short = name.split(' · ')[0] || routerId
  return (
    <nav className="sections" aria-label={`${short} sections`}>
      {own.map(([key, label, to]) => (
        <Link key={key} to={to} aria-current={key === current ? 'page' : undefined}>
          {label}
        </Link>
      ))}
      {fallback.map((p) => (
        <Link
          key={p.path}
          to={`${base}/luci?page=${encodeURIComponent(p.path)}`}
          aria-current={current === 'luci' && luciPath === p.path ? 'page' : undefined}
        >
          LuCI: {p.title}
        </Link>
      ))}
    </nav>
  )
}
