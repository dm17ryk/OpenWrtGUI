import { type ReactNode, useState } from 'react'
import type { OptionRow } from '../api/types'
import { optionKey } from './options'

const SHOWN = 40
type Filter = 'set' | 'all' | 'writer'

function valueText(v: OptionRow['value']): string {
  return Array.isArray(v) ? v.join(' ') : (v ?? '')
}

function Editor({ row, edit, onEdit }: { row: OptionRow; edit: string | undefined; onEdit: (value: string) => void }) {
  const current = edit ?? valueText(row.value)
  if (row.editor === 'readonly') return <span className="mono">{current || '—'}</span>
  if (row.editor === 'switch') {
    return (
      <select className="in" aria-label={row.name} value={current} onChange={(e) => onEdit(e.target.value)}>
        <option value="">default</option>
        <option value="1">on</option>
        <option value="0">off</option>
      </select>
    )
  }
  const placeholder = row.editor === 'secret' ? 'hidden' : row.editor === 'list' ? 'default · a b c' : 'default'
  return (
    <input
      className="in"
      aria-label={row.name}
      type={row.editor === 'secret' ? 'password' : 'text'}
      inputMode={row.editor === 'number' ? 'numeric' : undefined}
      value={current}
      placeholder={placeholder}
      onChange={(e) => onEdit(e.target.value)}
    />
  )
}

type Props = {
  rows: OptionRow[]
  edits: Record<string, string>
  onEdit: (key: string, value: string) => void
  /** Shown before the search box (e.g. the radio / SSID choice). */
  lead?: ReactNode
}

/** A router's typed option list as editors: search, a filter, and one editor per option. */
export function OptionsTable({ rows, edits, onEdit, lead }: Props) {
  const [filter, setFilter] = useState<Filter>('set')
  const [search, setSearch] = useState('')
  const visible = rows.filter(
    (r) =>
      (filter === 'all' || (filter === 'set' ? r.set_in_config || optionKey(r) in edits : r.writer !== null)) &&
      (!search || r.name.includes(search.trim().toLowerCase())),
  )
  return (
    <>
      <div className="row">
        {lead}
        <input className="in" aria-label="Find an option" placeholder="Find an option" value={search} onChange={(e) => setSearch(e.target.value)} />
        <div className="seg" role="group" aria-label="Show">
          {(
            [
              ['set', 'Set in config'],
              ['all', 'All'],
              ['writer', 'Set by a harness'],
            ] as const
          ).map(([key, text]) => (
            <button key={key} type="button" className={filter === key ? 'on' : ''} aria-pressed={filter === key} onClick={() => setFilter(key)}>
              {text}
            </button>
          ))}
        </div>
        <span className="muted">
          {visible.length} of {rows.length} options
        </span>
      </div>
      <div className="scroll-x">
        <table className="tbl" aria-label="All options">
          <thead>
            <tr>
              <th>Option</th>
              <th>Type</th>
              <th>Value</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {visible.slice(0, SHOWN).map((r) => (
              <tr key={optionKey(r)}>
                <td className="mono">{r.name}</td>
                <td>
                  <span className="b neu mono">{r.type}</span>
                </td>
                <td>
                  <Editor row={r} edit={edits[optionKey(r)]} onEdit={(v) => onEdit(optionKey(r), v)} />
                </td>
                <td>
                  <span className="row" style={{ gap: 6 }}>
                    {r.control && <span className="muted">set above: {r.control}</span>}
                    {r.writer && <span className="b har">set by {r.writer}</span>}
                    {optionKey(r) in edits && <span className="b park">changed, not applied</span>}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {visible.length > SHOWN && <div className="muted">{visible.length - SHOWN} more: type in the search box to narrow the list.</div>}
      <div className="muted">
        Empty value = not in the config, so the default applies. The list comes from the router, so a newer image brings its own options without an app update.
      </div>
    </>
  )
}
