import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { ApiError, apiFetch } from '../../api/client'
import type { GuardOut, SmsDone, SmsList, SmsMessage } from '../../api/types'
import { PreviewApply } from '../../components/PreviewApply'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { guardReasonText } from '../../shell/guardText'
import { GSM_RULE, isSendable, MAX_TEXT, TARGET, TARGET_RULE } from './sms'

type Storage = SmsList['storage']

const STORAGES: ReadonlyArray<readonly [Storage, string]> = [
  ['sim', 'SIM'],
  ['me', 'Phone memory'],
]
const STALE = 'The message list changed; preview again'

function countsLine(list: SmsList): string {
  const sim = list.storage === 'sim'
  if (list.full) return `${sim ? 'SIM' : 'Phone memory'} full: new messages cannot arrive until some are deleted`
  if (list.used == null || list.capacity == null) return `The app could not read how many messages the ${sim ? 'SIM' : 'phone memory'} holds`
  return `${list.used} of ${list.capacity} ${sim ? 'on the SIM' : 'in the phone memory'}`
}

function messageWord(n: number): string {
  return `${n} ${n === 1 ? 'message' : 'messages'}`
}

function errorText(err: unknown): string {
  return err instanceof ApiError ? err.detail : String(err)
}

/**
 * The modem's messages: the list and Read work during a harness run (they only read); Delete and Send go
 * through preview + digest + Apply and wait for the run to end (E5, E6, E7).
 */
export function SmsCard({ routerId }: { routerId: string; routerName: string }) {
  const client = useQueryClient()
  const guard = useQuery({ queryKey: ['guard'], queryFn: () => apiFetch<GuardOut>('/api/guard') })
  const live = guard.data?.live ?? false
  const runTitle = live && guard.data ? `Waits for the run: ${guardReasonText(guard.data)}` : undefined
  const [storage, setStorage] = useState<Storage>('sim')
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set())
  const [reading, setReading] = useState<number | null>(null)
  const listKey = ['lte-sms', routerId, storage]
  const list = useQuery({
    queryKey: listKey,
    queryFn: () => apiFetch<SmsList>(`/api/routers/${routerId}/lte/sms?storage=${storage}`),
  })
  const message = useQuery({
    queryKey: ['lte-sms-message', routerId, storage, reading],
    queryFn: () => apiFetch<SmsMessage>(`/api/routers/${routerId}/lte/sms/${storage}/${reading}`),
    enabled: reading !== null,
  })
  const ids = list.data?.ids ?? []
  const chosen = ids.filter((id) => selected.has(id))
  const base = `/api/routers/${routerId}/lte/sms`

  const del = usePlanApply<SmsDone>(
    `${base}/delete`,
    live || chosen.length === 0 ? null : { storage, ids: chosen },
    () => {
      setSelected(new Set())
      setReading(null)
      void client.invalidateQueries({ queryKey: listKey })
    },
    // a delete that failed part-way already removed messages (its done commands are in `lines`): refresh too
    (r) => r.ok || r.lines.length > 0,
  )
  // after a 409 the ticks are void: the list is read again (below) and the user chooses again
  const [seenError, setSeenError] = useState<string | null>(null)
  if (del.error !== seenError) {
    setSeenError(del.error)
    if (del.error === STALE) setSelected(new Set())
  }
  useEffect(() => {
    if (!del.error) return
    void client.invalidateQueries({ queryKey: ['lte-sms', routerId] })
  }, [del.error, client, routerId])

  const [number, setNumber] = useState('')
  const [text, setText] = useState('')
  const [sendBody, setSendBody] = useState<{ target: string; text: string } | null>(null)
  const send = usePlanApply<SmsDone>(
    `${base}/send`,
    live ? null : sendBody,
    () => {
      setNumber('')
      setText('')
      setSendBody(null)
    },
    (r) => r.ok,
  )
  const numberOk = TARGET.test(number)
  const textOk = isSendable(text)
  const edit = (set: () => void): void => {
    set()
    setSendBody(null)
    send.clear()
  }

  const pickStorage = (next: Storage): void => {
    setStorage(next)
    setSelected(new Set())
    setReading(null)
    del.clear()
  }
  const toggle = (id: number): void => {
    del.clear()
    setSelected((now) => {
      const next = new Set(now)
      if (!next.delete(id)) next.add(id)
      return next
    })
  }

  return (
    <section className="card stack" aria-labelledby="lte-sms-h">
      <div className="hrow">
        <h2 id="lte-sms-h">SMS</h2>
        <Help topic={HELP.lteSms} />
      </div>
      <div className="seg" role="group" aria-label="SMS storage">
        {STORAGES.map(([s, label]) => (
          <button key={s} type="button" className={storage === s ? 'on' : ''} aria-pressed={storage === s} onClick={() => pickStorage(s)}>
            {label}
          </button>
        ))}
        <button type="button" onClick={() => void client.invalidateQueries({ queryKey: listKey })}>
          Refresh
        </button>
      </div>
      {list.isError && (
        <div className="note x" role="alert">
          {errorText(list.error)}
        </div>
      )}
      {list.data && <span className={list.data.full ? 'b bad' : 'muted'}>{countsLine(list.data)}</span>}
      {list.data && ids.length === 0 && <span className="muted">No messages</span>}
      {ids.length > 0 && (
        <ul className="stack" style={{ gap: 4, listStyle: 'none', padding: 0, margin: 0 }}>
          {ids.map((id) => (
            <li key={id} className="row">
              <label className="row" style={{ gap: 6 }}>
                <input type="checkbox" aria-label={`Select message ${id}`} checked={selected.has(id)} onChange={() => toggle(id)} />
                <span>Message {id}</span>
              </label>
              <button type="button" onClick={() => setReading(id)}>
                Read
              </button>
            </li>
          ))}
        </ul>
      )}
      {reading !== null && message.isError && (
        <div className="note x" role="alert">
          {errorText(message.error)}
        </div>
      )}
      {reading !== null && message.data && (
        <div className="stack" role="region" aria-label={`Message ${reading}`} style={{ gap: 2 }}>
          <span className="b">{message.data.sender ?? 'Unknown sender'}</span>
          <span className="muted">{message.data.time ?? 'Time not known'}</span>
          {message.data.part && <span className="muted">{`Part ${message.data.part}`}</span>}
          <span style={{ whiteSpace: 'pre-wrap' }}>{message.data.text ?? ''}</span>
        </div>
      )}
      {live && guard.data && (
        <div className="note w">A harness run is live ({guardReasonText(guard.data)}): Delete and Send wait for it to end.</div>
      )}
      {chosen.length > 0 && (
        <PreviewApply
          heading="Delete preview"
          lines={del.plan?.lines ?? []}
          warnings={del.plan?.warnings ?? []}
          error={del.error}
          isBusy={del.isBusy}
          isDisabled={live}
          applyLabel={`Delete ${messageWord(chosen.length)}`}
          onApply={() => void del.apply()}
          helpTopic={HELP.lteSms}
        />
      )}
      {chosen.length === 0 && del.error && (
        <div className="note x" role="alert">
          {del.error}
        </div>
      )}
      {del.result?.ok && <div className="note" role="status">Deleted</div>}
      {del.result && !del.result.ok && (
        <div className="note x" role="alert">
          {del.result.error ?? 'The modem did not delete the messages'}
        </div>
      )}

      <div className="stack" role="group" aria-labelledby="lte-sms-send-h">
        <h3 id="lte-sms-send-h">Send SMS</h3>
        <label className="stack" style={{ gap: 2 }}>
          <span className="muted">Number</span>
          <input
            className="in mono"
            aria-label="Number"
            inputMode="tel"
            autoComplete="off"
            maxLength={16}
            disabled={send.isBusy}
            value={number}
            onChange={(e) => edit(() => setNumber(e.target.value))}
          />
        </label>
        {number !== '' && !numberOk && <div className="note w">{TARGET_RULE}</div>}
        <label className="stack" style={{ gap: 2 }}>
          <span className="muted">Text</span>
          <textarea className="in" aria-label="Text" rows={3} disabled={send.isBusy} value={text} onChange={(e) => edit(() => setText(e.target.value))} />
        </label>
        <span className={text.length > MAX_TEXT ? 'b bad' : 'muted'}>{`${text.length} / ${MAX_TEXT}`}</span>
        {text !== '' && !textOk && <div className="note w">{GSM_RULE}</div>}
        <div className="row">
          <button
            type="button"
            disabled={!numberOk || !textOk || live || send.isBusy}
            title={runTitle}
            onClick={() => setSendBody({ target: number, text })}
          >
            Preview
          </button>
        </div>
        {sendBody && (
          <PreviewApply
            heading="Send preview"
            lines={send.plan?.lines ?? []}
            warnings={send.plan?.warnings ?? []}
            error={send.error}
            isBusy={send.isBusy}
            isDisabled={live}
            applyLabel="Send"
            onApply={() => void send.apply()}
            helpTopic={HELP.lteSms}
          />
        )}
        {send.result?.ok && <div className="note" role="status">SMS sent</div>}
        {send.result && !send.result.ok && (
          <div className="note x" role="alert">
            {send.result.error ?? 'The modem did not send the SMS'}
          </div>
        )}
      </div>
    </section>
  )
}
