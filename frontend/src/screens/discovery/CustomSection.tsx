import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { ApiError, apiFetch } from '../../api/client'
import type { CustomRow, DiscoveryState, GuardOut, ProgramRow, ToolCard } from '../../api/types'
import { PreviewApply } from '../../components/PreviewApply'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import { guardReasonText } from '../../shell/guardText'
import { PromoteDialog } from './PromoteDialog'
import { ServicesTable } from './ServicesTable'
import { RunResult, ToolCardView } from './ToolCardView'
import { toolsPath, useRunOutput } from './useRunOutput'

const SCREENS: Record<string, string> = { ports: 'Ports', wifi: 'Wi-Fi', net: 'Network', firewall: 'Firewall', rf: 'RF live' }

type Promote = { path: string; usage: string | null; initial?: ToolCard }
type Writes = { live: boolean; busyTitle?: string }

function HelpRun({ routerId, path, onPromote }: { routerId: string; path: string; onPromote: (usage: string) => void }) {
  const run = useRunOutput(`/api/routers/${routerId}/discovery/help`, { path })
  return (
    <div className="stack" style={{ gap: 6 }}>
      <PreviewApply
        heading="Command that will run"
        lines={run.plan?.lines ?? []}
        warnings={run.plan?.warnings ?? []}
        error={run.error}
        isBusy={run.isBusy}
        applyLabel="Run"
        onApply={() => void run.run()}
        helpTopic={HELP.runHelp}
      />
      {run.output && (
        <>
          <RunResult output={run.output} />
          <div>
            <button className="btn" type="button" onClick={() => onPromote(run.output?.output ?? '')}>
              Promote from this output
            </button>
          </div>
        </>
      )}
    </div>
  )
}

type ProgramProps = { routerId: string; program: ProgramRow; hasActions: boolean; writes: Writes; onPromote: (p: Promote) => void }

function ProgramItem({ routerId, program, hasActions, writes, onPromote }: ProgramProps) {
  const [isAsking, setAsking] = useState(false)
  return (
    <li className="stack" style={{ gap: 6 }}>
      <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
        <span className="mono" style={{ overflowWrap: 'anywhere' }}>
          {program.path}
        </span>
        {program.has_card && <span className="b air">card below</span>}
        {hasActions && !program.has_card && (
          <>
            <span className="b park">no card yet</span>
            <span className="spacer" />
            <HelpTip topic={HELP.runHelp}>
              <button className="btn" type="button" disabled={writes.live} title={writes.live ? writes.busyTitle : undefined} onClick={() => setAsking(true)}>
                Run --help
              </button>
            </HelpTip>
            <HelpTip topic={HELP.promote}>
              <button className="btn" type="button" onClick={() => onPromote({ path: program.path, usage: program.usage })}>
                Promote
              </button>
            </HelpTip>
          </>
        )}
      </div>
      {program.usage && (
        <pre className="code" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
          {program.usage}
        </pre>
      )}
      {isAsking && !writes.live && <HelpRun routerId={routerId} path={program.path} onPromote={(usage) => onPromote({ path: program.path, usage })} />}
    </li>
  )
}

function PackageChip({ routerId, row, state }: { routerId: string; row: CustomRow; state: DiscoveryState }) {
  if (row.card && row.card !== 'promoted') {
    return (
      <Link className="b air" to={`/routers/${routerId}/${row.card}`}>
        {SCREENS[row.card] ?? row.card} screen
      </Link>
    )
  }
  if (row.card === 'promoted') return <span className="b air">card below</span>
  if (row.service) {
    const running = state.services.find((s) => s.name === row.service)?.running
    return <span className="b">service {running === true ? 'running' : running === false ? 'stopped' : ''}</span>
  }
  return <span className="b park">no card yet</span>
}

/** Your custom packages and the programs added after flashing (spec 7.8): usage, Run --help, Promote, services. */
export function CustomSection({ routerId, state }: { routerId: string; state: DiscoveryState }) {
  const client = useQueryClient()
  const guard = useQuery({ queryKey: ['guard'], queryFn: () => apiFetch<GuardOut>('/api/guard') })
  const tools = useQuery({ queryKey: ['tools', state.board], queryFn: () => apiFetch<ToolCard[]>(toolsPath(state.board)) })
  const [promote, setPromote] = useState<Promote | null>(null)
  const [error, setError] = useState<string | null>(null)
  const live = guard.data?.live ?? false
  const writes: Writes = { live, busyTitle: live && guard.data ? `Waits for the run: ${guardReasonText(guard.data)}` : undefined }
  const refresh = (): void => {
    void client.invalidateQueries({ queryKey: ['tools', state.board] })
    void client.invalidateQueries({ queryKey: ['discovery', routerId] })
  }
  const remove = async (card: ToolCard): Promise<void> => {
    setError(null)
    try {
      await apiFetch<null>(`${toolsPath(state.board)}?path=${encodeURIComponent(card.path)}`, { method: 'DELETE' })
      refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err))
    }
  }
  return (
    <section className="card stack" aria-labelledby="custom-h">
      <div className="hrow">
        <h2 id="custom-h">Your custom packages</h2>
        <Help topic={HELP.customPackages} />
      </div>
      {live && guard.data && (
        <div className="note w">
          A harness run is live ({guardReasonText(guard.data)}): Run --help, card commands and services wait for it to end.
        </div>
      )}
      {state.custom.length === 0 && <div className="muted">The image has no custom packages.</div>}
      <ul className="plain stack">
        {state.custom.map((row) => (
          <li key={row.package} className="stack" style={{ gap: 6 }}>
            <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
              <strong>{row.package}</strong>
              <span className="muted">{row.version}</span>
              {row.source !== 'image' && <span className="muted">{row.source}</span>}
              <PackageChip routerId={routerId} row={row} state={state} />
            </div>
            {row.description && <div className="muted">{row.description}</div>}
            <ul className="plain stack">
              {row.programs.map((p) => (
                <ProgramItem key={p.path} routerId={routerId} program={p} hasActions={row.card === null && row.service === null} writes={writes} onPromote={setPromote} />
              ))}
            </ul>
          </li>
        ))}
      </ul>
      <div className="hrow">
        <h3>Programs added after flashing</h3>
        <Help topic={HELP.programs} />
      </div>
      {state.programs.length === 0 && <div className="muted">No program was added after flashing.</div>}
      <ul className="plain stack">
        {state.programs.map((p) => (
          <ProgramItem key={p.path} routerId={routerId} program={p} hasActions writes={writes} onPromote={setPromote} />
        ))}
      </ul>
      {promote && (
        <PromoteDialog
          board={state.board}
          path={promote.path}
          usage={promote.usage}
          initial={promote.initial}
          onClose={() => setPromote(null)}
          onSaved={() => {
            setPromote(null)
            refresh()
          }}
        />
      )}
      {(tools.data ?? []).map((card) => (
        <ToolCardView
          key={card.path}
          routerId={routerId}
          card={card}
          live={live}
          busyTitle={writes.busyTitle}
          onEdit={(c) => setPromote({ path: c.path, usage: null, initial: c })}
          onRemove={(c) => void remove(c)}
        />
      ))}
      {error && <div className="note x">{error}</div>}
      <ServicesTable routerId={routerId} services={state.services} readAt={state.read_at} live={live} busyTitle={writes.busyTitle} />
    </section>
  )
}
