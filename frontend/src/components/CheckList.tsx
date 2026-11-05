import type { ApplyResult } from '../api/types'

function headline(result: ApplyResult): [string, string] {
  if (!result.applied) return ['b bad', `Not applied: ${result.error ?? 'the router refused the change'}`]
  if (result.verified) return ['b air', 'Applied and proven on air']
  const failed = result.checks.filter((c) => c.ok === false).map((c) => c.name)
  return ['b park', `Applied, not verified: ${result.error ?? failed.join(', ')}`]
}

/** What an Apply proved: one line per check, with what the router reported. */
export function CheckList({ result }: { result: ApplyResult }) {
  const [tone, text] = headline(result)
  return (
    <div className="stack" style={{ gap: 8 }} role="status" aria-label="Apply result">
      <span className={tone}>{text}</span>
      {result.checks.length > 0 && (
        <ul className="checks">
          {result.checks.map((c) => (
            <li key={c.name} className={c.ok === true ? 'ok' : c.ok === false ? 'bad' : 'skip'}>
              <span aria-hidden="true">{c.ok === true ? '✓' : c.ok === false ? '✗' : '–'}</span>
              <span>{c.name}</span>
              <span className="muted">{c.ok === null ? c.detail || 'not run' : c.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
