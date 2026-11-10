import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { HttpState, SystemAccessState } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

type Draft = { redirect: boolean; luci: boolean | null }

const draftOf = (http: HttpState): Draft => ({ redirect: http.redirect_https, luci: http.luci_on_network })

type Props = { routerId: string; short: string; access: SystemAccessState }

/** LuCI's HTTP(S) Access page (D6): the redirect to HTTPS, and whether LuCI answers on the network. */
export function HttpCard({ routerId, short, access }: Props) {
  const client = useQueryClient()
  const { http } = access
  const [seen, setSeen] = useState(http)
  const [draft, setDraft] = useState<Draft>(() => draftOf(http))
  if (seen !== http) {
    // uhttpd's settings changed (an apply, a read again): start from them
    setSeen(http)
    setDraft(draftOf(http))
  }
  const body: { redirect_https?: boolean; luci_on_network?: boolean } = {}
  if (draft.redirect !== http.redirect_https) body.redirect_https = draft.redirect
  if (draft.luci !== null && draft.luci !== http.luci_on_network) body.luci_on_network = draft.luci
  const pending = Object.keys(body).length > 0 ? body : null
  const change = usePlanApply(`/api/routers/${routerId}/system/http`, pending, () => {
    void client.invalidateQueries({ queryKey: ['system-access', routerId] })
  })
  const noHttps = !access.https_served && !http.redirect_https
  return (
    <section className="card stack" aria-labelledby="system-http-h">
      <div className="hrow">
        <h2 id="system-http-h">HTTP(S) access</h2>
        <Help topic={HELP.systemHttp} />
      </div>
      <label className="row" style={{ gap: 6 }}>
        <input type="checkbox" checked={draft.redirect} disabled={noHttps} onChange={(e) => setDraft({ ...draft, redirect: e.target.checked })} />
        Redirect HTTP to HTTPS
      </label>
      {noHttps && <div className="muted">{short} serves no HTTPS: nothing listens on its HTTPS port.</div>}
      <label className="row" style={{ gap: 6 }}>
        <input type="checkbox" checked={draft.luci ?? true} onChange={(e) => setDraft({ ...draft, luci: e.target.checked })} />
        LuCI on the network
      </label>
      {http.luci_on_network === null && (
        <div className="note">
          uhttpd keeps its own addresses ({[...http.listen_http, ...http.listen_https].join(', ') || 'none'}). Turning LuCI on or off here replaces them.
        </div>
      )}
      {draft.luci === false && <div className="muted">Off: only the router itself reaches LuCI. LuCI pages in this app keep working.</div>}
      <NetChange change={change} short={short} helpTopic={HELP.systemHttp} show={pending !== null} />
    </section>
  )
}
