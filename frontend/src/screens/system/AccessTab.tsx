import { useQuery } from '@tanstack/react-query'
import { ApiError, apiFetch } from '../../api/client'
import type { RepoKey, SystemAccessState } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { HttpCard } from './HttpCard'
import { PasswordCard, PolicyCard } from './PasswordCard'
import { SshCard } from './SshCard'
import { SshKeysCard } from './SshKeysCard'

function RepoKeysCard({ keys }: { keys: RepoKey[] }) {
  return (
    <section className="card stack" aria-labelledby="system-repo-h">
      <div className="hrow">
        <h2 id="system-repo-h">Repository keys</h2>
        <Help topic={HELP.systemRepoKeys} />
      </div>
      <div className="muted">The keys the package manager trusts. Read only: this app does not change them.</div>
      {keys.length === 0 ? (
        <div className="muted">No repository keys found.</div>
      ) : (
        <ul aria-label="Repository keys">
          {keys.map((k) => (
            <li key={`${k.kind} ${k.name}`} className="mono">
              {k.name} ({k.kind})
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

type Props = { routerId: string; routerName: string }

/** LuCI's Administration pages (spec 7.11, D2-D7): the root password, SSH, keys, HTTP(S), repository keys. */
export function AccessTab({ routerId, routerName }: Props) {
  const short = routerName.split(' · ')[0] || routerId
  const access = useQuery({ queryKey: ['system-access', routerId], queryFn: () => apiFetch<SystemAccessState>(`/api/routers/${routerId}/system/access`) })
  if (access.error) return <div className="note x">{access.error instanceof ApiError ? access.error.detail : access.error.message}</div>
  if (!access.data) return <div className="muted">Reading the access settings…</div>
  const state = access.data
  const props = { routerId, short, access: state }
  return (
    <>
      {state.missing.length > 0 && <div className="note w">No answer from the router for: {state.missing.join(', ')}</div>}
      <PasswordCard {...props} />
      <PolicyCard {...props} />
      <SshCard {...props} />
      <SshKeysCard {...props} />
      <HttpCard {...props} />
      <RepoKeysCard keys={state.repo_keys} />
    </>
  )
}
