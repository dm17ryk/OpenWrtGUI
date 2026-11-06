import { useState } from 'react'
import type { CustomFile, CustomIn, FirewallState } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'

type Props = { routerId: string; short: string; state: FirewallState; onApplied: () => void }
type Open = { was: CustomFile | null; name: string; content: string; remove: boolean }

function request(open: Open): CustomIn | null {
  if (open.remove && open.was) return { name: open.was.name, content: null }
  if (!open.name.trim()) return null
  if (open.was && open.content === open.was.content) return null
  return { name: open.was?.name ?? open.name.trim(), content: open.content }
}

/** Custom rules (`/etc/nftables.d/*.nft`, loaded into fw4's table): each file, its edit and fw4's check. */
export function CustomTab({ routerId, short, state, onApplied }: Props) {
  const [open, setOpen] = useState<Open | null>(null)
  const body = open ? request(open) : null
  const change = usePlanApply(`/api/routers/${routerId}/firewall/custom`, body, () => {
    setOpen(null)
    onApplied()
  })
  const label = open?.was ? open.was.name : 'the new file'
  return (
    <section className="card stack" aria-labelledby="fw-custom-h">
      <div className="hrow">
        <h2 id="fw-custom-h">Custom rules</h2>
        <Help topic={HELP.fwCustom} />
        <span className="muted">nftables snippets fw4 loads on every start</span>
        <span className="spacer" />
        <HelpTip topic={HELP.fwCustom}>
          <button className="btn" type="button" onClick={() => setOpen({ was: null, name: '', content: '', remove: false })}>
            + Include
          </button>
        </HelpTip>
      </div>
      <div className="scroll-x">
        <table className="tbl" aria-label="Custom rules files">
          <thead>
            <tr>
              <th>File</th>
              <th>Loaded at</th>
              <th>Owner</th>
              <th>Lines</th>
              <th>
                <span className="sr-only">Edit</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {state.custom.map((f) => (
              <tr key={f.path}>
                <td className="mono">{f.path}</td>
                <td className="mono">inside table inet fw4</td>
                <td>{f.from_image ? <span className="b neu">from the image</span> : <span className="b own">added after flashing</span>}</td>
                <td className="mono">{f.comments_only ? `${f.lines} · comments only` : f.lines}</td>
                <td>
                  <button className="btn" type="button" onClick={() => setOpen({ was: f, name: f.name, content: f.content, remove: false })}>
                    Edit
                  </button>
                </td>
              </tr>
            ))}
            {state.custom.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  No files in /etc/nftables.d.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="note">Edits are checked with nft -c before fw4 restarts, and the restart runs with the 60 s rollback.</div>
      {open && (
        <fieldset className="stack editor" aria-label={open.was ? `File ${open.was.name}` : 'New rules file'}>
          <legend>{open.was ? open.was.path : 'New rules file'}</legend>
          {!open.was && (
            <label className="field">
              <span>File name</span>
              <input className="in mono" value={open.name} onChange={(e) => setOpen({ ...open, name: e.target.value })} />
              <span className="muted small mono">/etc/nftables.d/{open.name || '<name>'}.nft</span>
            </label>
          )}
          <textarea
            className="in mono"
            aria-label={`Rules in ${label}`}
            rows={12}
            spellCheck={false}
            value={open.content}
            onChange={(e) => setOpen({ ...open, content: e.target.value })}
          />
          <div className="row">
            {open.was && (
              <button className="btn danger" type="button" aria-pressed={open.remove} onClick={() => setOpen({ ...open, remove: !open.remove })}>
                {open.remove ? 'Keep this file' : 'Delete file'}
              </button>
            )}
            <button className="btn" type="button" onClick={() => setOpen(null)}>
              Cancel
            </button>
          </div>
        </fieldset>
      )}
      <NetChange change={change} short={short} helpTopic={HELP.fwCustom} show={body !== null} />
    </section>
  )
}
