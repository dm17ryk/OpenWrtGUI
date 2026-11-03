import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { RouterItem } from '../api/types'
import { hhmm, routerState } from './routerState'

type Row = { key: string; tag: string; tagClass: string; text: ReactNode; action?: ReactNode }

function rows(items: RouterItem[]): Row[] {
  const out: Row[] = []
  for (const item of items) {
    const { record, health } = item
    const state = routerState(item)
    if (state === 'needs app key') {
      out.push({
        key: `${record.id}-key`,
        tag: record.name,
        tagClass: 'b neu',
        text: 'no app key yet. Installing it adds one line to authorized_keys; password login keeps working.',
        action: (
          <Link className="btn" to={`/add?host=${encodeURIComponent(record.host)}`}>
            Install key
          </Link>
        ),
      })
    } else if (state === 'unreachable' && health.error?.includes('host key')) {
      out.push({
        key: `${record.id}-hostkey`,
        tag: record.name,
        tagClass: 'b bad',
        text: `host key changed: ${health.error}`,
        action: (
          <Link className="btn" to={`/add?host=${encodeURIComponent(record.host)}`}>
            Check and re-pin
          </Link>
        ),
      })
    } else if (state === 'unreachable') {
      out.push({
        key: `${record.id}-down`,
        tag: record.name,
        tagClass: 'b bad',
        text: `unreachable since ${hhmm(health.since)}: ${health.error ?? 'no answer'}`,
      })
    }
  }
  return out
}

export function Attention({ items }: { items: RouterItem[] }) {
  const list = rows(items)
  if (list.length === 0) return null
  return (
    <section className="card" aria-labelledby="attention-h">
      <h2 id="attention-h" style={{ marginBottom: 12 }}>
        Needs attention
      </h2>
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {list.map((row) => (
          <div key={row.key} className="row" style={{ padding: '12px 0', borderTop: '1px solid var(--line2)' }}>
            <span className={row.tagClass}>{row.tag}</span>
            <span style={{ flex: '1 1 320px' }}>{row.text}</span>
            {row.action}
          </div>
        ))}
      </div>
    </section>
  )
}
