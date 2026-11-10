import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, postJson } from '../../api/client'
import type { NetApplyResult, NetPlan, PasswordPolicy, SystemAccessState } from '../../api/types'
import { type PlanApply, usePlanApply } from '../../components/usePlanApply'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { NetChange } from '../net/NetChange'
import { usePreview } from '../wifi/usePreview'

const NO_POLICY: PasswordPolicy = { enabled: false, pw_length: 0, digits: false, uc_lc: false, special_characters: false }

/** What the router's policy asks of a new password, as a sentence; null while the policy is off. */
function policyRules(policy: PasswordPolicy | null): string | null {
  if (!policy?.enabled) return null
  const rules = [
    policy.pw_length > 0 ? `at least ${policy.pw_length} characters` : null,
    policy.digits ? 'a digit' : null,
    policy.uc_lc ? 'upper and lower case letters' : null,
    policy.special_characters ? 'a special character' : null,
  ].filter((r): r is string => r !== null)
  return rules.length > 0 ? `The router's password policy asks for ${rules.join(', ')}.` : "The router's password policy is on and asks for nothing more."
}

/**
 * The password change: the preview carries no password (it is `passwd root` whatever the password is), and
 * Apply sends the password once, with the preview's digest. `onSent` runs whenever the router answered.
 */
function usePasswordChange(base: string, password: string, isReady: boolean, onSent: (result: NetApplyResult) => void): PlanApply {
  const preview = usePreview<NetPlan>(`${base}/preview`, isReady ? {} : null)
  const [isBusy, setBusy] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)
  const [result, setResult] = useState<NetApplyResult | null>(null)
  const plan = preview?.plan ?? null
  const apply = async (): Promise<void> => {
    if (!plan) return
    setBusy(true)
    setApplyError(null)
    setResult(null)
    try {
      const done = await postJson<NetApplyResult>(`${base}/apply`, { password, digest: plan.digest })
      setResult(done)
      onSent(done)
    } catch (err) {
      setApplyError(err instanceof ApiError ? err.detail : String(err)) // a refusal names the rule, never the password
    } finally {
      setBusy(false)
    }
  }
  const clear = (): void => {
    setResult(null)
    setApplyError(null)
  }
  return { plan, error: applyError ?? preview?.error ?? null, isBusy, result, apply, clear }
}

type Props = { routerId: string; short: string; access: SystemAccessState }

/** root's password (D2): typed twice, kept in this component only, cleared once the router answered. */
export function PasswordCard({ routerId, short, access }: Props) {
  const client = useQueryClient()
  const [password, setPassword] = useState('')
  const [again, setAgain] = useState('')
  const isReady = password !== '' && password === again
  const change = usePasswordChange(`/api/routers/${routerId}/system/password`, password, isReady, () => {
    setPassword('')
    setAgain('')
    void client.invalidateQueries({ queryKey: ['system-access', routerId] })
  })
  const rules = policyRules(access.policy)
  return (
    <section className="card stack" aria-labelledby="system-password-h">
      <div className="hrow">
        <h2 id="system-password-h">Router password</h2>
        <Help topic={HELP.systemPassword} />
      </div>
      {access.password === 'set' && <div className="muted">{short} has a root password. LuCI and password SSH logins use it.</div>}
      {access.password === 'none' && <div className="note w">{short} has no root password: anyone on its network can open LuCI. Set one here.</div>}
      {rules && <div className="note">{rules}</div>}
      <div className="grid">
        <label className="field">
          <span>New password</span>
          <input className="in mono" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        <label className="field">
          <span>Confirm the password</span>
          <input className="in mono" type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} />
        </label>
      </div>
      {password !== '' && again !== '' && password !== again && <div className="note x">The two passwords differ.</div>}
      <NetChange change={change} short={short} helpTopic={HELP.systemPassword} show={isReady} applyLabel="Set the password" provenText="Password changed" />
    </section>
  )
}

const same = (a: PasswordPolicy, b: PasswordPolicy): boolean =>
  a.enabled === b.enabled && a.pw_length === b.pw_length && a.digits === b.digits && a.uc_lc === b.uc_lc && a.special_characters === b.special_characters

/** LuCI's Password Policy page: the rules a new password must meet (rpcd.policy). */
export function PolicyCard({ routerId, short, access }: Props) {
  const client = useQueryClient()
  const [seen, setSeen] = useState(access.policy)
  const [draft, setDraft] = useState<PasswordPolicy>(access.policy ?? NO_POLICY)
  if (seen !== access.policy) {
    // the router's policy changed (an apply, a read again): start from it
    setSeen(access.policy)
    setDraft(access.policy ?? NO_POLICY)
  }
  const body = same(draft, access.policy ?? NO_POLICY) ? null : draft
  const change = usePlanApply(`/api/routers/${routerId}/system/password-policy`, body, () => {
    void client.invalidateQueries({ queryKey: ['system-access', routerId] })
  })
  const set = (patch: Partial<PasswordPolicy>): void => setDraft({ ...draft, ...patch })
  const flag = (key: 'enabled' | 'digits' | 'uc_lc' | 'special_characters', text: string) => (
    <label className="row" style={{ gap: 6 }}>
      <input type="checkbox" checked={draft[key]} onChange={(e) => set({ [key]: e.target.checked })} />
      {text}
    </label>
  )
  return (
    <section className="card stack" aria-labelledby="system-policy-h">
      <div className="hrow">
        <h2 id="system-policy-h">Password policy</h2>
        <Help topic={HELP.systemPolicy} />
      </div>
      {access.policy === null && <div className="muted">{short} has no password policy yet: Apply creates one.</div>}
      <div className="row">{flag('enabled', 'Check new passwords against this policy')}</div>
      <label className="field" style={{ maxWidth: 220 }}>
        <span>Minimum length</span>
        <input className="in mono" type="number" min={0} max={128} value={String(draft.pw_length)} onChange={(e) => set({ pw_length: Number(e.target.value) || 0 })} />
      </label>
      <div className="row">
        {flag('digits', 'A digit')}
        {flag('uc_lc', 'Upper and lower case letters')}
        {flag('special_characters', 'A special character')}
      </div>
      <NetChange change={change} short={short} helpTopic={HELP.systemPolicy} show={body !== null} />
    </section>
  )
}
