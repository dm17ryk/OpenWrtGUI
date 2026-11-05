type Result = {
  applied: boolean
  verified: boolean
  error: string | null
  checks: { name: string; ok: boolean | null; detail: string }[]
}

function headline(result: Result, provenText: string): [string, string] {
  if (!result.applied) return ['b bad', `Not applied: ${result.error ?? 'the router refused the change'}`]
  if (result.verified) return ['b air', provenText]
  const failed = result.checks.filter((c) => c.ok === false).map((c) => c.name)
  return ['b park', `Applied, not verified: ${result.error ?? failed.join(', ')}`]
}

type Props = { result: Result; provenText?: string }

/** What an Apply proved: one line per check, with what the router reported. */
export function CheckList({ result, provenText = 'Applied and proven on air' }: Props) {
  const [tone, text] = headline(result, provenText)
  return (
    <div className="stack" style={{ gap: 8 }} role="status" aria-label="Apply result">
      <span className={tone}>{text}</span>
      {result.verified && result.error && <div className="note w">{result.error}</div>}
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
