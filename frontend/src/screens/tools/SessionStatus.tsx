import type { ReactNode } from 'react'
import type { ToolSessionView } from '../../api/types'

function clock(t: number): string {
  return new Date(t * 1000).toLocaleTimeString('en-GB', { hour12: false })
}

/**
 * The newest run of a router tool (v1.2b R2): running with Stop, or how it ended; the page's own results; the
 * tool's lines the page did not read as results.
 */
export function SessionStatus({ session, onStop, children }: { session: ToolSessionView; onStop: () => void; children?: ReactNode }) {
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="row" style={{ gap: 12 }}>
        <span className="eyebrow">{session.running ? `Running until ${clock(session.ends_at)}` : 'Last run'}</span>
        {session.running && (
          <button className="btn" type="button" onClick={onStop}>
            Stop
          </button>
        )}
      </div>
      {session.error && (
        <div className="note x" role="alert">
          {session.error}
        </div>
      )}
      {children}
      {session.notes.length > 0 && <div className="code">{session.notes.join('\n')}</div>}
    </div>
  )
}
