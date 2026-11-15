import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch } from '../../api/client'
import type { FstabState, MountState } from '../../api/types'
import { usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'
import { FstabCard } from './FstabCard'
import { mib } from './live'

type Props = { routerId: string; routerName: string }

// LuCI's mounts.js offers no Unmount for these
const PROTECTED = /^\/(overlay|rom|tmp(\/.+)?|dev(\/.+)?|)$/

/** LuCI's Mount Points page: what is mounted where and how full it is; with block-mount, fstab too (v1.0a2 D5). */
export function MountsTab({ routerId, routerName }: Props) {
  const short = routerName.split(' · ')[0] || routerId
  const client = useQueryClient()
  const state = useQuery({ queryKey: ['system-mounts', routerId], queryFn: () => apiFetch<MountState>(`/api/routers/${routerId}/system/mounts`) })
  const block = state.data?.block ?? false
  const fstab = useQuery({
    queryKey: ['system-fstab', routerId],
    queryFn: () => apiFetch<FstabState>(`/api/routers/${routerId}/system/fstab`),
    enabled: block,
  })
  const [unmount, setUnmount] = useState<string | null>(null)
  const unmounting = usePlanApply(`/api/routers/${routerId}/system/fstab/unmount`, unmount ? { target: unmount } : null, () => {
    setUnmount(null)
    void client.invalidateQueries({ queryKey: ['system-mounts', routerId] })
  })
  const usage = new Map((state.data?.usage ?? []).map((u) => [u.target, u]))
  return (
    <section className="card stack" aria-labelledby="system-mounts-h">
      <div className="row">
        <div className="hrow">
          <h2 id="system-mounts-h">Mount points</h2>
          <Help topic={HELP.systemMounts} />
        </div>
        <div className="spacer" />
        <button type="button" className="btn" onClick={() => void state.refetch()}>
          Read again
        </button>
      </div>
      {state.error && <div className="note x">{state.error instanceof ApiError ? state.error.detail : state.error.message}</div>}
      {state.isPending && <div className="muted">Reading the mounts…</div>}
      {state.data && !block && <div className="note">fstab editing needs the block-mount package, which this image does not have.</div>}
      {state.data && (
        <div className="scroll-x">
          <table className="tbl" aria-label="Mount points">
            <thead>
              <tr>
                <th>Mount point</th>
                <th>Device</th>
                <th>Type</th>
                <th>Size</th>
                <th>Used</th>
                <th>Free</th>
                <th>Use</th>
                {block && <th />}
              </tr>
            </thead>
            <tbody>
              {state.data.mounts.map((m) => {
                const u = usage.get(m.target)
                return (
                  <tr key={`${m.target} ${m.device}`}>
                    <td className="mono">{m.target}</td>
                    <td>
                      <span className="mono">{m.device}</span>
                      <div className="muted mono">{m.options}</div>
                    </td>
                    <td className="mono">{m.fstype}</td>
                    <td>{u ? mib(u.size_kib * 1024) : '—'}</td>
                    <td>{u ? mib(u.used_kib * 1024) : '—'}</td>
                    <td>{u ? mib(u.available_kib * 1024) : '—'}</td>
                    <td>{u ? `${u.use_pct}%` : '—'}</td>
                    {block && (
                      <td>
                        {!PROTECTED.test(m.target) && (
                          <button type="button" className="btn" aria-label={`Unmount ${m.target}`} onClick={() => setUnmount(m.target)}>
                            Unmount
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <NetChange change={unmounting} short={short} helpTopic={HELP.systemMounts} show={unmount !== null} />
      {fstab.error && <div className="note x">{fstab.error instanceof ApiError ? fstab.error.detail : fstab.error.message}</div>}
      {fstab.data?.block && <FstabCard routerId={routerId} short={short} state={fstab.data} />}
    </section>
  )
}
