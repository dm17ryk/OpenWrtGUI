import { useQuery } from '@tanstack/react-query'
import { ApiError, apiFetch } from '../../api/client'
import type { MountState } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { mib } from './live'

type Props = { routerId: string }

/** LuCI's Mount Points page, read only (D8): what is mounted where, and how full each file system is. */
export function MountsTab({ routerId }: Props) {
  const state = useQuery({ queryKey: ['system-mounts', routerId], queryFn: () => apiFetch<MountState>(`/api/routers/${routerId}/system/mounts`) })
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
      {state.data && !state.data.block && <div className="note">fstab editing needs the block-mount package, which this image does not have.</div>}
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
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
