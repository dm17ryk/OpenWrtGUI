import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { ApiError, apiFetch, postJson } from '../../api/client'
import type { BridgeClosed, BridgeView, GuardOut, RouterDetail, UciChange } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { RouterSections } from '../../shell/RouterSections'
import { useLuciPages } from './pages'

const CHANGES_POLL_MS = 5000
const WRITE_TEXT =
  "This is LuCI's own page, shown inside the app, for a feature with no screen here yet. Changes made here skip the app's preview and its 60 s rollback; LuCI applies them with its own rollback. The app shows what changed below."
const READ_TEXT =
  "This is LuCI's own page, shown inside the app. A harness run is in progress, so the session can only read: LuCI shows the page but cannot save."

type Session = { view: BridgeView | null; ended: boolean; alive: boolean }

function detailOf(err: unknown): string {
  return err instanceof ApiError ? err.detail : String(err)
}

function closeQuietly(routerId: string, bridgeId: string): void {
  postJson(`/api/routers/${routerId}/luci/bridges/${bridgeId}/close`).catch(() => undefined)
}

function ChangesCard({ changes, isEnded }: { changes: UciChange[]; isEnded: boolean }) {
  const none = isEnded
    ? 'Nothing changed.'
    : 'Nothing yet. Press Save & Apply in the page above to see how a change shows up here.'
  return (
    <section className="card stack" aria-labelledby="luci-changes-h">
      <div className="row" style={{ alignItems: 'baseline' }}>
        <div className="hrow">
          <h2 id="luci-changes-h">Changed via LuCI since you opened this page</h2>
          <Help topic={HELP.luciChanged} />
        </div>
        <span className="muted">the app compares the config before and after; it cannot preview LuCI's changes</span>
      </div>
      {changes.length === 0 ? (
        <div className="muted">{none}</div>
      ) : (
        <div className="scroll-x">
          <table className="tbl">
            <thead>
              <tr>
                <th>Option</th>
                <th>Before</th>
                <th>After</th>
                <th>
                  <span className="sr-only">Source</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {changes.map((c) => (
                <tr key={c.option}>
                  <td className="mono">{c.option}</td>
                  <td className="mono">{c.before ?? '(not set)'}</td>
                  <td className="mono">{c.after ?? '(removed)'}</td>
                  <td>
                    <span className="b park">changed via LuCI</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function LuciBridge({ routerId, path }: { routerId: string; path: string }) {
  const session = useRef<Session | null>(null)
  const [view, setView] = useState<BridgeView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [final, setFinal] = useState<UciChange[] | null>(null)
  const [sawRun, setSawRun] = useState(false)
  const detail = useQuery({ queryKey: ['router', routerId], queryFn: () => apiFetch<RouterDetail>(`/api/routers/${routerId}`) })
  const guard = useQuery({ queryKey: ['guard'], queryFn: () => apiFetch<GuardOut>('/api/guard') })
  const pages = useLuciPages(routerId)
  const changes = useQuery({
    queryKey: ['luci-changes', view?.id],
    queryFn: () => apiFetch<UciChange[]>(`/api/routers/${routerId}/luci/bridges/${view?.id}/changes`),
    enabled: view !== null && final === null,
    refetchInterval: CHANGES_POLL_MS,
    retry: false,
  })

  useEffect(() => {
    const s: Session = { view: null, ended: false, alive: true }
    session.current = s
    postJson<BridgeView>(`/api/routers/${routerId}/luci/open`, { path }).then(
      (v) => {
        s.view = v
        if (s.alive) setView(v)
        else closeQuietly(routerId, v.id) // left before it opened
      },
      (err: unknown) => {
        if (s.alive) setError(detailOf(err))
      },
    )
    return () => {
      s.alive = false
      if (s.view && !s.ended) {
        s.ended = true
        closeQuietly(routerId, s.view.id)
      }
    }
  }, [routerId, path])

  // The app turns an open page read-only when a run starts and never back, so neither does this view.
  if (view && guard.data?.live && !sawRun) setSawRun(true)

  const handleClose = async (): Promise<void> => {
    const s = session.current
    if (!s?.view || s.ended) return
    s.ended = true
    try {
      const closed = await postJson<BridgeClosed>(`/api/routers/${routerId}/luci/bridges/${s.view.id}/close`)
      setFinal(closed.changes)
    } catch (err) {
      setError(detailOf(err))
      setFinal(changes.data ?? [])
    }
  }

  const record = detail.data?.record
  const short = record?.name.split(' · ')[0] ?? routerId
  const page = view?.page ?? pages.data?.find((p) => p.path === path)
  const title = page?.title ?? path
  const readOnly = view?.access === 'read' || sawRun
  const ended = final !== null
  return (
    <main className="wrap">
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <div>
          <div className="eyebrow">
            {short} · <span className="mono">{record?.host ?? ''}</span> · LuCI page
            {page?.section ? ` · ${page.section}` : ''}
          </div>
          <div className="hrow">
            <h1>{title}</h1>
            <Help topic={HELP.luci} />
          </div>
        </div>
        <div className="spacer" />
        <Link className="btn" to={`/routers/${routerId}`}>
          Back to the router
        </Link>
        <button className="btn" type="button" disabled={!view || ended} onClick={() => void handleClose()}>
          Close and end session
        </button>
      </div>
      <RouterSections routerId={routerId} name={record?.name ?? routerId} current="luci" luciPath={path} />
      {error && <div className="note x">{error}</div>}
      {view && !ended && (
        <>
          <div className="note luci-strip" role="note">
            <span className="luci-strip-text">{readOnly ? READ_TEXT : WRITE_TEXT}</span>
            <Help topic={readOnly ? HELP.luciReadOnly : HELP.luciOpen} />
            <span className={readOnly ? 'b har' : 'b park'}>
              {readOnly ? 'read-only session' : `can change: ${title} settings`}
            </span>
            <span className="b neu">session ends 5 min idle or on close</span>
          </div>
          <iframe className="luci-frame" title={`LuCI page ${title}`} src={view.url} />
        </>
      )}
      {!view && !error && <div className="muted">Opening the LuCI page…</div>}
      {ended && (
        <div className="note">
          <div className="hrow">
            <strong>Session ended</strong>
            <Help topic={HELP.luciSession} />
          </div>
          The LuCI session on {short} is closed. Open the page again from the router's sections to make more changes.
        </div>
      )}
      {view && <ChangesCard changes={final ?? changes.data ?? []} isEnded={ended} />}
    </main>
  )
}

/** A LuCI page with no screen here yet, shown inside the app (route /routers/:id/luci?page=<path>). */
export function LuciPage() {
  const { id = '' } = useParams()
  const [params] = useSearchParams()
  const path = params.get('page') ?? ''
  return <LuciBridge key={`${id}:${path}`} routerId={id} path={path} />
}
