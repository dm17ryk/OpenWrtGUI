import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, putJson } from '../../api/client'
import type { SshKeyRow, SystemAccessState } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

function Chip({ row }: { row: SshKeyRow }) {
  if (row.label === 'app') return <span className="b air">App</span>
  if (row.label === 'harness') return <span className="b park">Harness · {row.owner}</span>
  return <span className="b">Other</span>
}

const nameOf = (row: SshKeyRow): string => row.comment || row.fingerprint || `line ${row.index + 1}`

type OwnerProps = { routerId: string; row: SshKeyRow; onDone: () => void }

/** Names the harness a key belongs to (kept in the app's settings, nothing is sent to the router). */
function OwnerForm({ routerId, row, onDone }: OwnerProps) {
  const client = useQueryClient()
  const [owner, setOwner] = useState(row.owner ?? '')
  const [error, setError] = useState<string | null>(null)
  const save = async (value: string | null): Promise<void> => {
    try {
      const state = await putJson<SystemAccessState>(`/api/routers/${routerId}/system/ssh-keys/owner`, { fingerprint: row.fingerprint, owner: value })
      client.setQueryData(['system-access', routerId], state)
      onDone()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err))
    }
  }
  return (
    <div className="stack" style={{ gap: 6 }}>
      <label className="field">
        <span>Owner of {nameOf(row)}</span>
        <input className="in" maxLength={40} value={owner} placeholder="the harness that logs in with it" onChange={(e) => setOwner(e.target.value)} />
      </label>
      {error && <div className="note x">{error}</div>}
      <div className="row" style={{ gap: 6 }}>
        <button type="button" className="btn pri" disabled={!owner.trim()} onClick={() => void save(owner.trim())}>
          Save owner
        </button>
        {row.owner && (
          <button type="button" className="btn" onClick={() => void save(null)}>
            Forget owner
          </button>
        )}
        <button type="button" className="btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </div>
  )
}

type Props = { routerId: string; short: string; access: SystemAccessState }

/** /etc/dropbear/authorized_keys (D5): who may log in with a key. The app's own key cannot be removed here. */
export function SshKeysCard({ routerId, short, access }: Props) {
  const client = useQueryClient()
  const [seen, setSeen] = useState(access.keys)
  const [removed, setRemoved] = useState<string[]>([])
  const [isAdding, setAdding] = useState(false)
  const [pasted, setPasted] = useState('')
  const [owning, setOwning] = useState<string | null>(null)
  if (seen !== access.keys) {
    // the router's keys changed (an apply, a read again): start from them
    setSeen(access.keys)
    setRemoved([])
    setPasted('')
    setAdding(false)
  }
  const add = pasted.split('\n').map((l) => l.trim()).filter(Boolean)
  const body = add.length > 0 || removed.length > 0 ? { add, remove: removed } : null
  const change = usePlanApply(`/api/routers/${routerId}/system/ssh-keys`, body, () => {
    void client.invalidateQueries({ queryKey: ['system-access', routerId] })
  })
  const toggle = (fingerprint: string): void =>
    setRemoved(removed.includes(fingerprint) ? removed.filter((f) => f !== fingerprint) : [...removed, fingerprint])
  return (
    <section className="card stack" aria-labelledby="system-keys-h">
      <div className="hrow">
        <h2 id="system-keys-h">SSH keys</h2>
        <Help topic={HELP.systemSshKeys} />
      </div>
      {access.keys.length === 0 && <div className="muted">{short} has no authorized keys: only password logins work.</div>}
      <div className="scroll-x">
        <table className="tbl" aria-label="SSH keys">
          <thead>
            <tr>
              <th>Type</th>
              <th>Comment</th>
              <th>Fingerprint</th>
              <th>Used by</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {access.keys.map((row) => {
              const fingerprint = row.fingerprint
              const isGone = fingerprint !== null && removed.includes(fingerprint)
              return (
                <tr key={row.index} className={isGone ? 'flag' : undefined}>
                  <td className="mono">{row.type ?? 'not a key'}</td>
                  <td>
                    {row.comment}
                    {row.options && <div className="muted mono">{row.options}</div>}
                  </td>
                  <td className="mono">{fingerprint ?? 'kept as written'}</td>
                  <td>{fingerprint && <Chip row={row} />}</td>
                  <td>
                    {fingerprint && row.label !== 'app' && (
                      <div className="stack" style={{ gap: 6 }}>
                        <div className="row" style={{ gap: 6 }}>
                          <button type="button" className="btn" onClick={() => setOwning(owning === fingerprint ? null : fingerprint)}>
                            Owner…
                          </button>
                          <button type="button" className="btn" aria-pressed={isGone} onClick={() => toggle(fingerprint)}>
                            {isGone ? 'Keep' : 'Remove'}
                          </button>
                        </div>
                        {owning === fingerprint && <OwnerForm routerId={routerId} row={row} onDone={() => setOwning(null)} />}
                      </div>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {isAdding ? (
        <label className="field">
          <span>Public key line</span>
          <textarea className="in mono" rows={3} spellCheck={false} placeholder="ssh-ed25519 AAAA… user@pc" value={pasted} onChange={(e) => setPasted(e.target.value)} />
        </label>
      ) : (
        <div className="row">
          <button type="button" className="btn" onClick={() => setAdding(true)}>
            Add key
          </button>
        </div>
      )}
      <NetChange change={change} short={short} helpTopic={HELP.systemSshKeys} show={body !== null} />
    </section>
  )
}
