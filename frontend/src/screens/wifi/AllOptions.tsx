import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { ApiError, apiFetch, postJson } from '../../api/client'
import type { ApplyResult, OptionRow, RadioState } from '../../api/types'
import { CheckList } from '../../components/CheckList'
import { PreviewApply } from '../../components/PreviewApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { usePreview } from './usePreview'

const SHOWN = 40
type Filter = 'set' | 'all' | 'writer'
type Edit = { section: string; name: string; value: string | string[] | null }

const keyOf = (r: { section: string; name: string }): string => `${r.section}.${r.name}`

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
  const placeholder = row.editor === 'secret' ? 'hidden' : row.editor === 'list' ? 'driver default · a b c' : 'driver default'
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

type Props = { routerId: string; radio: RadioState; short: string; onApplied: () => void }

export function AllOptions({ routerId, radio, short, onApplied }: Props) {
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [group, setGroup] = useState(radio.name)
  const [filter, setFilter] = useState<Filter>('set')
  const [search, setSearch] = useState('')
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [applyError, setApplyError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<ApplyResult | null>(null)
  const rows = useQuery({
    queryKey: ['wifi-options', routerId, radio.name],
    queryFn: () => apiFetch<OptionRow[]>(`/api/routers/${routerId}/wifi/options?radio=${encodeURIComponent(radio.name)}`),
    enabled: open,
  })
  const all = useMemo(() => rows.data ?? [], [rows.data])
  const groups = [radio.name, ...radio.ssids.map((s) => s.section)]
  const visible = all.filter(
    (r) =>
      r.section === group &&
      (filter === 'all' || (filter === 'set' ? r.set_in_config : r.writer !== null)) &&
      (!search || r.name.includes(search.trim().toLowerCase())),
  )
  const body = useMemo(() => {
    const list: Edit[] = Object.entries(edits).map(([key, raw]) => {
      const row = all.find((r) => keyOf(r) === key)
      const [section, ...rest] = key.split('.')
      const value = raw === '' ? null : row?.editor === 'list' ? raw.split(/\s+/).filter(Boolean) : raw
      return { section, name: rest.join('.'), value }
    })
    return list.length > 0 ? { radio: radio.name, edits: list } : null
  }, [edits, all, radio.name])

  const preview = usePreview(`/api/routers/${routerId}/wifi/options/preview`, body)
  const plan = preview?.plan ?? null
  const error = applyError ?? preview?.error ?? null

  const apply = async (): Promise<void> => {
    if (!body || !plan) return
    setBusy(true)
    setApplyError(null)
    try {
      setResult(await postJson<ApplyResult>(`/api/routers/${routerId}/wifi/options/apply`, { ...body, digest: plan.digest }))
      setEdits({})
      await client.invalidateQueries({ queryKey: ['wifi-options', routerId, radio.name] })
      onApplied()
    } catch (err) {
      setApplyError(err instanceof ApiError ? err.detail : String(err))
    } finally {
      setBusy(false)
    }
  }

  const label = (section: string): string => {
    const n = all.filter((r) => r.section === section).length
    const ssid = radio.ssids.find((s) => s.section === section)
    return `${ssid ? `SSID ${ssid.ssid}` : `Radio ${section}`}${n ? ` · ${n}` : ''}`
  }

  return (
    <section className="card stack" aria-labelledby="options-h">
      <div className="row">
        <div className="hrow">
          <h2 id="options-h">All options</h2>
          <Help topic={HELP.wifiOptions} />
        </div>
        <span className="muted">every option this radio and its SSIDs accept, from the router's own list</span>
        <div className="spacer" />
        <button className="btn" type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? 'Hide all options' : 'Show all options'}
        </button>
      </div>
      {open && (
        <>
          <div className="row">
            <div className="seg" role="group" aria-label="Option group">
              {groups.map((g) => (
                <button key={g} type="button" className={group === g ? 'on' : ''} aria-pressed={group === g} onClick={() => setGroup(g)}>
                  {label(g)}
                </button>
              ))}
            </div>
            <input className="in" aria-label="Find an option" placeholder="Find an option, e.g. beacon, rts, wmm" value={search} onChange={(e) => setSearch(e.target.value)} />
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
              {visible.length} of {all.filter((r) => r.section === group).length} options
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
                  <tr key={keyOf(r)}>
                    <td className="mono">{r.name}</td>
                    <td>
                      <span className="b neu mono">{r.type}</span>
                    </td>
                    <td>
                      <Editor row={r} edit={edits[keyOf(r)]} onEdit={(v) => setEdits({ ...edits, [keyOf(r)]: v })} />
                    </td>
                    <td>
                      <span className="row" style={{ gap: 6 }}>
                        {r.control && <span className="muted">set above: {r.control}</span>}
                        {r.writer && <span className="b har">set by {r.writer}</span>}
                        {keyOf(r) in edits && <span className="b park">changed, not applied</span>}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {visible.length > SHOWN && <div className="muted">{visible.length - SHOWN} more: type in the search box to narrow the list.</div>}
          <div className="muted">Empty value = not in the config, so the driver default applies. The list comes from the router, so a newer image brings its own options without an app update.</div>
          {(body || result) && (
            <div className="grid">
              <PreviewApply
                heading={`Commands that will run on ${short}`}
                lines={plan?.lines ?? []}
                warnings={plan?.warnings ?? []}
                error={error}
                isBusy={busy}
                applyLabel="Apply options"
                onApply={() => void apply()}
                helpTopic={HELP.wifiApply}
              />
              {result && <CheckList result={result} />}
            </div>
          )}
        </>
      )}
    </section>
  )
}
