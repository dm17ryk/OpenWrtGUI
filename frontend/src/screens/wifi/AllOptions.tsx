import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { ApiError, apiFetch, postJson } from '../../api/client'
import type { ApplyResult, OptionRow, RadioState } from '../../api/types'
import { CheckList } from '../../components/CheckList'
import { OptionsTable } from '../../components/OptionsTable'
import { editsBody } from '../../components/options'
import { PreviewApply } from '../../components/PreviewApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { usePreview } from './usePreview'

type Props = { routerId: string; radio: RadioState; short: string; onApplied: () => void }

export function AllOptions({ routerId, radio, short, onApplied }: Props) {
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [group, setGroup] = useState(radio.name)
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
  const body = useMemo(() => {
    const list = editsBody(edits, all)
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
  const groupSeg = (
    <div className="seg" role="group" aria-label="Option group">
      {groups.map((g) => (
        <button key={g} type="button" className={group === g ? 'on' : ''} aria-pressed={group === g} onClick={() => setGroup(g)}>
          {label(g)}
        </button>
      ))}
    </div>
  )

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
          <OptionsTable
            rows={all.filter((r) => r.section === group)}
            edits={edits}
            onEdit={(key, value) => setEdits({ ...edits, [key]: value })}
            lead={groupSeg}
          />
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
