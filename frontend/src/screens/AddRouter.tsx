import { useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { ApiError, apiFetch, postJson } from '../api/client'
import type { Preview, RouterRecord, SessionView } from '../api/types'
import { Help, HelpTip } from '../help/Help'
import { HELP } from '../help/topics'

const LABELS = ['Address', 'Host key', 'First login', 'Install key', 'Identify', 'Port map'] as const
const TITLES = [
  'Where is the router?',
  'Check the router is the one you mean',
  'Log in to the router',
  'Install the app’s key',
  'What is this router?',
  'Map the sockets',
] as const
const STEP_HELP = [HELP.stepAddress, HELP.stepHostKey, HELP.stepLogin, HELP.stepInstallKey, HELP.stepIdentify, HELP.stepIdentify] as const

function loginText(v: SessionView): string {
  if (v.key_path) return `this PC’s key ${v.key_path} already works; the app uses it and installed nothing`
  if (v.login_method === 'app_key') return 'the app key was already on the router and works'
  if (v.key_installed) return 'app key installed and working'
  return 'no app key: the app cannot reconnect until you install it'
}

function explain(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409 && err.body && typeof err.body === 'object' && 'expected' in err.body) {
      const body = err.body as { expected: string | null; actual?: { fingerprint?: string } }
      if (body.expected) return `The host key changed: pinned ${body.expected}, now ${body.actual?.fingerprint ?? '?'}. ${err.detail}`
    }
    return err.detail
  }
  return err instanceof Error ? err.message : String(err)
}

export function AddRouter() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const client = useQueryClient()
  const [step, setStep] = useState(0)
  const [host, setHost] = useState(params.get('host') ?? '')
  const [port, setPort] = useState('22')
  const [view, setView] = useState<SessionView | null>(null)
  const [trying, setTrying] = useState(false)
  const [autoFailed, setAutoFailed] = useState(false)
  const [username, setUsername] = useState('root')
  const [password, setPassword] = useState('')
  const [useKeyFile, setUseKeyFile] = useState(false)
  const [keyPath, setKeyPath] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [preview, setPreview] = useState<string[]>([])
  const [labels, setLabels] = useState<Record<string, string>>({})
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const sid = view?.sid ?? ''
  const run = async (action: () => Promise<void>): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(explain(err))
    } finally {
      setBusy(false)
    }
  }

  const connect = (e: FormEvent): void => {
    e.preventDefault()
    void run(async () => {
      setView(await postJson<SessionView>('/api/onboard', { host: host.trim(), port: Number(port) || 22 }))
      setStep(1)
    })
  }

  const identify = async (): Promise<void> => {
    const v = await postJson<SessionView>(`/api/onboard/${sid}/identify`)
    setView(v)
    setLabels(Object.fromEntries(Object.entries(v.proposed_port_labels).map(([k, val]) => [k, String(val)])))
    setName(v.summary?.hostname && v.summary.hostname !== 'OpenWrt' ? v.summary.hostname : '')
    setStep(4)
  }

  /** A key that already works skips the install step; any other login goes on to it. */
  const loggedIn = async (v: SessionView): Promise<void> => {
    setView(v)
    if (v.step === 'identify') {
      await identify()
    } else if (v.step === 'install_key') {
      setPreview((await apiFetch<Preview>(`/api/onboard/${sid}/install-key/preview`)).commands)
      setStep(3)
    }
  }

  const autoLogin = async (): Promise<void> => {
    setTrying(true)
    setAutoFailed(false)
    try {
      await loggedIn(await postJson<SessionView>(`/api/onboard/${sid}/auto-login`))
    } catch (err) {
      setAutoFailed(true)
      throw err
    } finally {
      setTrying(false)
    }
  }

  const trust = (): void =>
    void run(async () => {
      setView(await postJson<SessionView>(`/api/onboard/${sid}/trust`, { fingerprint: view?.host_key?.fingerprint }))
      setStep(2)
      await autoLogin()
    })

  const login = (e: FormEvent): void => {
    e.preventDefault()
    const body = useKeyFile ? { key_path: keyPath, username } : { password, username }
    setPassword('')
    void run(async () => loggedIn(await postJson<SessionView>(`/api/onboard/${sid}/login`, body)))
  }

  const setRootPassword = (e: FormEvent): void => {
    e.preventDefault()
    const pw = newPassword
    setNewPassword('')
    void run(async () => setView(await postJson<SessionView>(`/api/onboard/${sid}/set-password`, { password: pw })))
  }

  const installKey = (): void =>
    void run(async () => {
      await postJson<SessionView>(`/api/onboard/${sid}/install-key`)
      setView(await postJson<SessionView>(`/api/onboard/${sid}/verify`))
      await identify()
    })

  const skipKey = (): void => void run(identify)

  const finish = (e: FormEvent): void => {
    e.preventDefault()
    void run(async () => {
      const rec = await postJson<RouterRecord>(`/api/onboard/${sid}/finish`, { name, port_labels: labels })
      await client.invalidateQueries({ queryKey: ['routers'] })
      navigate(`/routers/${rec.id}`)
    })
  }

  let body: ReactNode = null
  if (step === 0) {
    body = (
      <form className="stack" onSubmit={connect}>
        <div className="grid">
          <div className="field">
            <label htmlFor="host">Router address</label>
            <input id="host" className="in mono" value={host} onChange={(e) => setHost(e.target.value)} placeholder="192.168.1.2" required />
          </div>
          <div className="field">
            <label htmlFor="port">SSH port</label>
            <input id="port" className="in mono" value={port} onChange={(e) => setPort(e.target.value)} inputMode="numeric" />
          </div>
        </div>
        <div>
          <button className="btn pri" type="submit" disabled={busy || !host.trim()}>
            Connect
          </button>
        </div>
      </form>
    )
  } else if (step === 1 && view?.host_key) {
    body = (
      <div className="stack">
        <div className="muted">The router sent this host key. Compare it with the router (for example on its serial console) before you pin it.</div>
        <dl className="kv">
          <dt>Key type</dt>
          <dd className="mono">{view.host_key.type}</dd>
          <dt>Fingerprint</dt>
          <dd className="mono" style={{ fontSize: 15 }}>
            {view.host_key.fingerprint}
          </dd>
        </dl>
        {view.changed_from && (
          <div className="note x">
            This address had a different key pinned ({view.changed_from}). A reflash makes a new key; anything else means you may not be talking to your router.
          </div>
        )}
        {view.known_before && <div className="note">This key is already pinned for this address.</div>}
        <div>
          <HelpTip topic={HELP.stepHostKey}>
            <button className="btn pri" type="button" onClick={trust} disabled={busy}>
              Accept and pin
            </button>
          </HelpTip>
        </div>
      </div>
    )
  } else if (step === 2 && trying) {
    body = (
      <div className="muted" role="status">
        Trying the app’s key, this PC’s keys and root / root…
      </div>
    )
  } else if (step === 2) {
    body = (
      <form className="stack" onSubmit={login}>
        {autoFailed ? (
          <div className="row" style={{ gap: 8 }}>
            <span className="muted">The automatic login stopped (the reason is above). Log in once yourself, or</span>
            <button className="btn" type="button" onClick={() => void run(autoLogin)} disabled={busy}>
              Try again
            </button>
          </div>
        ) : (
          <div className="muted">None of them worked: the app tried the app’s key, this PC’s keys and root / root. Log in once yourself.</div>
        )}
        <div className="seg" role="group" aria-label="How to log in">
          <button type="button" className={useKeyFile ? '' : 'on'} aria-pressed={!useKeyFile} onClick={() => setUseKeyFile(false)}>
            Password
          </button>
          <button type="button" className={useKeyFile ? 'on' : ''} aria-pressed={useKeyFile} onClick={() => setUseKeyFile(true)}>
            Use a key file I already have
          </button>
        </div>
        <div className="field">
          <label htmlFor="user">User</label>
          <input id="user" className="in mono" autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)} />
        </div>
        {useKeyFile ? (
          <div className="field">
            <label htmlFor="keyfile">Key file</label>
            <input id="keyfile" className="in mono" value={keyPath} onChange={(e) => setKeyPath(e.target.value)} placeholder="C:\Essence_SC\home\.ssh\id_rsa" />
          </div>
        ) : (
          <div className="field">
            <label htmlFor="pw">Password</label>
            <input id="pw" className="in" type="password" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} />
            <span className="muted">Used once to log in. It is never stored or logged. A fresh OpenWrt has no password: leave it empty.</span>
          </div>
        )}
        <div>
          <button className="btn pri" type="submit" disabled={busy}>
            Log in
          </button>
        </div>
      </form>
    )
  } else if (step === 3) {
    body = (
      <div className="stack">
        {view?.login_method === 'default_password' && (
          <div className="note">Logged in with the default root / root. Anyone on this network can do the same: think about changing it.</div>
        )}
        {view?.root_password === 'none' && (
          <form className="note w stack" onSubmit={setRootPassword}>
            <strong>This router has no root password.</strong>
            <div className="field">
              <label htmlFor="newpw">Set a root password</label>
              <input id="newpw" className="in" type="password" autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
            </div>
            <div>
              <button className="btn" type="submit" disabled={busy || !newPassword}>
                Set password
              </button>
            </div>
          </form>
        )}
        <div className="muted">The app adds its own key to the router. Existing keys and password login stay as they are. This is the exact command:</div>
        <div className="code">{preview.join('\n')}</div>
        <div className="row" style={{ gap: 8 }}>
          <HelpTip topic={HELP.stepInstallKey}>
            <button className="btn pri" type="button" onClick={installKey} disabled={busy}>
              Install key
            </button>
          </HelpTip>
          <HelpTip topic={HELP.skipKey}>
            <button className="btn" type="button" onClick={skipKey} disabled={busy}>
              Skip for now
            </button>
          </HelpTip>
        </div>
      </div>
    )
  } else if (step === 4 && view) {
    const s = view.summary
    body = (
      <div className="stack">
        {s ? (
          <dl className="kv">
            <dt>Model</dt>
            <dd>{s.model}</dd>
            <dt>Firmware</dt>
            <dd className="mono">
              {s.revision} · {s.target}
            </dd>
            <dt>Services</dt>
            <dd>{s.services} ubus services</dd>
            <dt>Wi-Fi options</dt>
            <dd>
              {Object.entries(s.wireless_options)
                .map(([radio, groups]) => `${radio}: radio ${groups.device ?? 0} · SSID ${groups.interface ?? 0}`)
                .join('; ') || 'no radios'}
            </dd>
            <dt>Login</dt>
            <dd>{loginText(view)}</dd>
          </dl>
        ) : (
          <div className="muted">The router described itself.</div>
        )}
        <div>
          <button className="btn pri" type="button" onClick={() => setStep(5)}>
            Continue
          </button>
        </div>
      </div>
    )
  } else if (step === 5) {
    body = (
      <form className="stack" onSubmit={finish}>
        <div className="field">
          <label htmlFor="name">Name</label>
          <input id="name" className="in" value={name} onChange={(e) => setName(e.target.value)} placeholder="AP4 · lab" />
        </div>
        <div className="muted">Proposed from the router’s board file. Change a label if your sockets are printed differently.</div>
        <div className="scroll-x">
          <table className="tbl">
            <thead>
              <tr>
                <th>Internal port</th>
                <th>Printed label</th>
              </tr>
            </thead>
            <tbody>
              {Object.keys(labels).length === 0 && (
                <tr>
                  <td colSpan={2} className="muted">
                    This router has no switch description; ports can be mapped later.
                  </td>
                </tr>
              )}
              {Object.entries(labels).map(([num, label]) => (
                <tr key={num}>
                  <td className="mono">{num}</td>
                  <td>
                    <input
                      className="in"
                      aria-label={`Label for internal port ${num}`}
                      value={label}
                      onChange={(e) => setLabels({ ...labels, [num]: e.target.value })}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <button className="btn pri" type="submit" disabled={busy}>
            Save port map
          </button>
        </div>
      </form>
    )
  }

  return (
    <main className="wrap">
      <div>
        <div className="eyebrow">Add router · step {step + 1} of {LABELS.length}</div>
        <div className="hrow">
          <h1>{TITLES[step]}</h1>
          <Help topic={STEP_HELP[step]} />
        </div>
      </div>
      <ol className="row" aria-label="Steps" style={{ listStyle: 'none', padding: 0, margin: 0, gap: 6 }}>
        {LABELS.map((label, i) => (
          <li key={label} className={i === step ? 'b own' : i < step ? 'b air' : 'b neu'} aria-current={i === step ? 'step' : undefined}>
            {i + 1} · {label}
          </li>
        ))}
      </ol>
      {error && (
        <div className="note x" role="alert">
          {error}
        </div>
      )}
      <section className="card" aria-labelledby="step-h">
        <h2 id="step-h" className="eyebrow" style={{ marginBottom: 12 }}>
          {LABELS[step]}
        </h2>
        {body}
      </section>
    </main>
  )
}
