import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch } from '../../api/client'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'

/** The whole nftables ruleset as the router lists it, read-only and refreshed every 5 s. */
export function RawTab({ routerId }: { routerId: string }) {
  const ruleset = useQuery({
    queryKey: ['firewall-ruleset', routerId],
    queryFn: () => apiFetch<{ text: string }>(`/api/routers/${routerId}/firewall/ruleset`),
    refetchInterval: 5000,
  })
  const [copied, setCopied] = useState(false)
  const text = ruleset.data?.text ?? ''
  const copy = async (): Promise<void> => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
  }
  return (
    <section className="card stack" aria-labelledby="fw-raw-h">
      <div className="hrow">
        <h2 id="fw-raw-h">Raw ruleset</h2>
        <Help topic={HELP.fwRaw} />
        <span className="muted">
          <span className="mono">nft -a list ruleset</span> · read-only · refreshed every 5 s
        </span>
        <span className="spacer" />
        {copied && <span className="muted small">Copied</span>}
        <HelpTip topic={HELP.fwRaw}>
          <button className="btn" type="button" disabled={!text} onClick={() => void copy()}>
            Copy
          </button>
        </HelpTip>
      </div>
      {ruleset.isError && <div className="note x">{ruleset.error instanceof ApiError ? ruleset.error.detail : String(ruleset.error)}</div>}
      <pre className="code" role="region" aria-label="Raw ruleset text" tabIndex={0}>
        {text}
      </pre>
    </section>
  )
}
