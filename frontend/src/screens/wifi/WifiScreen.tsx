import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useParams } from 'react-router'
import { ApiError, apiFetch, postJson } from '../../api/client'
import type { ApplyResult, RadioState, RouterDetail, WifiState } from '../../api/types'
import { CheckList } from '../../components/CheckList'
import { PreviewApply } from '../../components/PreviewApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { RouterSections } from '../../shell/RouterSections'
import { AllOptions } from './AllOptions'
import { ChannelCard } from './ChannelCard'
import { draftFrom, requestFrom, type Draft } from './draft'
import { ModeCard } from './ModeCard'
import { RadioFields } from './RadioFields'
import { StationsTable } from './StationsTable'
import { StepThroughCard } from './StepThroughCard'
import { usePreview } from './usePreview'
import { WhoMayJoin } from './WhoMayJoin'

const BANDS: ReadonlyArray<readonly [string, string]> = [
  ['2g', '2.4 GHz'],
  ['5g', '5 GHz'],
  ['6g', '6 GHz'],
]

function airBadge(radio: RadioState): [string, string] {
  if (!radio.up) return ['b park', 'parked']
  const a = radio.actual
  const width = a?.no_ht ? 'legacy' : a?.width_mhz === 40 ? 'HT40' : 'HT20'
  return ['b air', `on air · ch ${a?.channel ?? '?'} · ${width}`]
}

type PanelProps = {
  routerId: string
  short: string
  radio: RadioState
  result: ApplyResult | null
  onResult: (r: ApplyResult | null) => void
  onApplied: () => void
}

function RadioPanel({ routerId, short, radio, result, onResult, onApplied }: PanelProps) {
  const [draft, setDraft] = useState<Draft>(() => draftFrom(radio))
  const [busy, setBusy] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)
  const req = useMemo(() => requestFrom(radio, draft), [radio, draft])
  const preview = usePreview(`/api/routers/${routerId}/wifi/preview`, req)
  const plan = preview?.plan ?? null
  const error = applyError ?? preview?.error ?? null

  const apply = async (): Promise<void> => {
    if (!req || !plan) return
    setBusy(true)
    setApplyError(null)
    try {
      // the digest names the preview shown: the app refuses if the router changed since
      onResult(await postJson<ApplyResult>(`/api/routers/${routerId}/wifi/apply`, { ...req, digest: plan.digest }))
      onApplied()
    } catch (err) {
      setApplyError(err instanceof ApiError ? err.detail : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {radio.mask === 'missing' && (
        <div className="note w hrow">
          TX mask not active: the radio was reloaded since the last Apply. Apply again to restore it.
          <Help topic={HELP.wifiMask} />
        </div>
      )}
      <ModeCard draft={draft.modes} mcs={radio.limits.mcs} legacyRates={radio.legacy_rates} onChange={(modes) => setDraft({ ...draft, modes })} />
      <ChannelCard
        draft={draft.channels}
        band={radio.band}
        allowed={radio.limits.channels}
        country={radio.limits.country}
        onChange={(channels) => setDraft({ ...draft, channels })}
      />
      <RadioFields radio={radio} draft={draft} onChange={setDraft} />
      <section className="card stack" aria-labelledby="apply-h">
        <div className="hrow">
          <h2 id="apply-h">Apply</h2>
          <Help topic={HELP.wifiApply} />
        </div>
        <div className="grid">
          <PreviewApply
            heading={`Commands that will run on ${short}`}
            lines={plan?.lines ?? []}
            warnings={plan?.warnings ?? []}
            error={error}
            isBusy={busy}
            applyLabel={`Apply to ${short}`}
            onApply={() => void apply()}
            helpTopic={HELP.wifiApply}
          />
          <div className="stack" style={{ gap: 8 }}>
            <div className="muted">After Apply the app checks the result on air, not only in the config: radio up, channel, width, TX power, the TX mask, and the rate of real beacons.</div>
            {result && <CheckList result={result} />}
          </div>
        </div>
      </section>
    </>
  )
}

export function WifiScreen() {
  const { id = '' } = useParams()
  const client = useQueryClient()
  const [selected, setSelected] = useState<string | null>(null)
  const [result, setResult] = useState<ApplyResult | null>(null)
  const detail = useQuery({ queryKey: ['router', id], queryFn: () => apiFetch<RouterDetail>(`/api/routers/${id}`) })
  const wifi = useQuery({ queryKey: ['wifi', id], queryFn: () => apiFetch<WifiState>(`/api/routers/${id}/wifi`) })
  const name = detail.data?.record.name ?? id
  const short = name.split(' · ')[0] || id
  const radios = wifi.data?.radios ?? []
  const radio = radios.find((r) => r.name === selected) ?? radios[0]
  const refresh = (): void => {
    void client.invalidateQueries({ queryKey: ['wifi', id] })
    void client.invalidateQueries({ queryKey: ['stations', id] })
  }
  const [tone, badge] = radio ? airBadge(radio) : ['b neu', 'reading…']

  return (
    <main className="wrap">
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <div>
          <div className="eyebrow">
            <span className="mono">{detail.data?.record.host ?? ''}</span>
            {detail.data?.summary ? ` · ${detail.data.summary.model}` : ''}
          </div>
          <div className="hrow">
            <h1>Wi-Fi</h1>
            <Help topic={HELP.wifi} />
            <span className={tone}>{badge}</span>
          </div>
        </div>
      </div>
      <RouterSections routerId={id} name={name} current="wifi" />
      {wifi.isError && <div className="note x">{wifi.error instanceof ApiError ? wifi.error.detail : String(wifi.error)}</div>}
      {radio && (
        <>
          <div className="hrow">
            <div className="tabs" role="tablist" aria-label="Radios">
              {BANDS.flatMap(([band, label]) => {
                const here = radios.filter((r) => r.band === band)
                if (here.length === 0) {
                  return [
                    <button key={band} type="button" role="tab" className="tab" aria-selected={false} disabled>
                      {label} · no radio on this router
                    </button>,
                  ]
                }
                return here.map((r) => (
                  <button key={r.name} type="button" role="tab" className={`tab${r.name === radio.name ? ' on' : ''}`} aria-selected={r.name === radio.name} onClick={() => setSelected(r.name)}>
                    {label} · {r.name}
                  </button>
                ))
              })}
            </div>
            <Help topic={HELP.wifiRadios} />
          </div>
          <RadioPanel
            key={`${radio.name}-${wifi.dataUpdatedAt}`}
            routerId={id}
            short={short}
            radio={radio}
            result={result}
            onResult={setResult}
            onApplied={refresh}
          />
          <StepThroughCard key={`steps-${radio.name}`} routerId={id} short={short} radio={radio} onEnded={refresh} />
          <WhoMayJoin routerId={id} />
          <StationsTable routerId={id} short={short} />
          <AllOptions key={radio.name} routerId={id} radio={radio} short={short} onApplied={refresh} />
        </>
      )}
    </main>
  )
}
