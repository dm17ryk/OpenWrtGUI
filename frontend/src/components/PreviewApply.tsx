import { HelpTip } from '../help/Help'

type Props = {
  heading: string
  lines: string[]
  warnings: string[]
  error: string | null
  isBusy: boolean
  isDisabled?: boolean
  applyLabel: string
  onApply: () => void
  helpTopic: string
}

/** The exact commands a change will send, its warnings, and the button that sends them. */
export function PreviewApply({ heading, lines, warnings, error, isBusy, isDisabled = false, applyLabel, onApply, helpTopic }: Props) {
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="eyebrow">{heading}</div>
      {lines.length > 0 && (
        <div className="code" role="region" aria-label="Command preview" tabIndex={0}>
          {lines.join('\n')}
        </div>
      )}
      {warnings.map((w) => (
        <div key={w} className="note w">
          {w}
        </div>
      ))}
      {error && (
        <div className="note x" role="alert">
          {error}
        </div>
      )}
      <div className="row">
        <HelpTip topic={helpTopic}>
          <button className="btn pri" type="button" onClick={onApply} disabled={isBusy || isDisabled || lines.length === 0}>
            {isBusy ? 'Applying…' : applyLabel}
          </button>
        </HelpTip>
      </div>
    </div>
  )
}
