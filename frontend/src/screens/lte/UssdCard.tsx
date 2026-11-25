import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { apiFetch } from '../../api/client'
import type { GuardOut, UssdReply } from '../../api/types'
import { PreviewApply } from '../../components/PreviewApply'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { guardReasonText } from '../../shell/guardText'

// A copy of the server's rule (lte/commands.py): * or #, then digits, * or #, ending in #.
const CODE = /^[*#][0-9*#]{1,30}#$/
const CODE_RULE = 'A USSD code looks like *100#: * or #, digits, * or #, ending in #'
const LISTENING = "Listening for the network's reply (up to 35 s)…"

const STATUS_TEXT: Record<UssdReply['status'], string | null> = {
  reply: null,
  more: 'The network asked for more; menus are not supported, so the session was closed',
  ended: 'The network ended the session',
  'no reply': 'No reply in 35 s; the session was closed',
  error: null,
}

/**
 * Sends one USSD code and shows the network's one reply. Preview, then Apply, which listens up to 35 s; every
 * answer ends the exchange, so a menu is never followed (E8, E9).
 */
export function UssdCard({ routerId }: { routerId: string; routerName: string }) {
  const guard = useQuery({ queryKey: ['guard'], queryFn: () => apiFetch<GuardOut>('/api/guard') })
  const live = guard.data?.live ?? false
  const runTitle = live && guard.data ? `Waits for the run: ${guardReasonText(guard.data)}` : undefined
  const [code, setCode] = useState('')
  const [body, setBody] = useState<{ code: string } | null>(null)
  const ussd = usePlanApply<UssdReply>(
    `/api/routers/${routerId}/lte/ussd`,
    live ? null : body,
    () => {},
    () => true,
  )
  const codeOk = CODE.test(code)
  const reply = ussd.result
  const note = reply ? STATUS_TEXT[reply.status] : null

  return (
    <section className="card stack" aria-labelledby="lte-ussd-h">
      <div className="hrow">
        <h2 id="lte-ussd-h">USSD</h2>
        <Help topic={HELP.lteUssd} />
      </div>
      <label className="stack" style={{ gap: 2 }}>
        <span className="muted">Code</span>
        <input
          className="in mono"
          aria-label="USSD code"
          autoComplete="off"
          maxLength={32}
          value={code}
          onChange={(e) => {
            setCode(e.target.value)
            setBody(null)
            ussd.clear()
          }}
        />
      </label>
      {code !== '' && !codeOk && <div className="note w">{CODE_RULE}</div>}
      <div className="row">
        <button type="button" disabled={!codeOk || live} title={runTitle} onClick={() => setBody({ code })}>
          Preview
        </button>
      </div>
      {body && !live && (
        <PreviewApply
          heading="Send preview"
          lines={ussd.plan?.lines ?? []}
          warnings={ussd.plan?.warnings ?? []}
          error={ussd.error}
          isBusy={ussd.isBusy}
          applyLabel="Send USSD"
          onApply={() => void ussd.apply()}
          helpTopic={HELP.lteUssd}
        />
      )}
      {ussd.isBusy && <div className="note" role="status">{LISTENING}</div>}
      {reply && reply.status === 'error' && (
        <div className="note x" role="alert">
          {reply.text ?? 'The modem refused the code'}
        </div>
      )}
      {reply && reply.status !== 'error' && (
        <div className="stack" role="region" aria-label="USSD reply" style={{ gap: 2 }}>
          {reply.text && <span style={{ whiteSpace: 'pre-wrap' }}>{reply.text}</span>}
          {note && <span className="muted">{note}</span>}
        </div>
      )}
    </section>
  )
}
