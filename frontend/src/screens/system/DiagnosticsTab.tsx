import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch, postJson } from '../../api/client'
import type { DiagResult, DiagTool, GuardOut } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { guardReasonText } from '../../shell/guardText'

const TOOLS: ReadonlyArray<readonly [DiagTool, string]> = [
  ['ping', 'Ping'],
  ['traceroute', 'Traceroute'],
  ['nslookup', 'Nslookup'],
]

/** Ping, traceroute and nslookup on the router (D4): no preview, audited, waiting while a run is live. */
export function DiagnosticsTab({ routerId }: { routerId: string }) {
  const guard = useQuery({ queryKey: ['guard'], queryFn: () => apiFetch<GuardOut>('/api/guard') })
  const live = guard.data?.live ?? false
  const [tool, setTool] = useState<DiagTool>('ping')
  const [target, setTarget] = useState('')
  const [result, setResult] = useState<DiagResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isBusy, setBusy] = useState(false)
  const host = target.trim()

  const run = async (): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      setResult(await postJson<DiagResult>(`/api/routers/${routerId}/system/diagnose`, { tool, target: host }))
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card stack" aria-labelledby="system-diag-h">
      <div className="hrow">
        <h2 id="system-diag-h">Diagnostics</h2>
        <Help topic={HELP.systemDiagnostics} />
      </div>
      <div className="row">
        <div className="seg" role="group" aria-label="Tool">
          {TOOLS.map(([key, label]) => (
            <button key={key} type="button" className={tool === key ? 'on' : ''} aria-pressed={tool === key} onClick={() => setTool(key)}>
              {label}
            </button>
          ))}
        </div>
        <input
          className="in mono"
          style={{ flex: 1 }}
          aria-label="Target"
          placeholder="host name or address"
          maxLength={253}
          autoComplete="off"
          spellCheck={false}
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && host && !live && !isBusy) void run()
          }}
        />
        <button className="btn pri" type="button" disabled={!host || live || isBusy} onClick={() => void run()}>
          {isBusy ? 'Running…' : 'Run'}
        </button>
      </div>
      {live && guard.data && <div className="note w">A diagnostic sends traffic from the router, so it waits for the run: {guardReasonText(guard.data)}.</div>}
      {error && <div className="note x">{error}</div>}
      {result && (
        <pre className="code" role="log" aria-label="Diagnostic output">
          <span className="mono">{`$ ${result.command}`}</span>
          {`\n${result.output}`}
          {result.exit_status !== 0 && <span className="muted">{`\nexit ${result.exit_status}`}</span>}
        </pre>
      )}
    </section>
  )
}
