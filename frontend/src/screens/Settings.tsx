import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { ApiError, apiFetch, downloadFile, postJson, putJson } from '../api/client'
import type { AppInfo, AppKeyOut, GuardWatchList, Settings, UpdateOut } from '../api/types'

type Progress = { version: string; done: number; total: number }
type WatchKey = 'lock_files' | 'processes' | 'router_ssids'

const WATCH: ReadonlyArray<{ key: WatchKey; title: string; noun: string }> = [
  { key: 'lock_files', title: 'Lock files', noun: 'lock file' },
  { key: 'processes', title: 'Processes on this PC', noun: 'process' },
  { key: 'router_ssids', title: 'SSIDs on air on a router', noun: 'router SSID' },
]
const RETENTION: ReadonlyArray<readonly [Settings['audit_retention_days'], string]> = [
  [30, '30 days'],
  [90, '90 days'],
  [365, '1 year'],
  [0, 'Forever'],
]

function mb(bytes: number): string {
  return `${(bytes / 1_000_000).toFixed(1)} MB`
}

function WatchGroup({ title, noun, items, onChange }: { title: string; noun: string; items: string[]; onChange: (next: string[]) => void }) {
  const [value, setValue] = useState('')
  const id = `add-${noun.replace(/\s+/g, '-')}`
  const add = (e: FormEvent): void => {
    e.preventDefault()
    const v = value.trim()
    setValue('')
    if (v && !items.includes(v)) onChange([...items, v])
  }
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="eyebrow">{title}</div>
      <div className="row" style={{ gap: 6 }}>
        {items.length === 0 && <span className="muted">none</span>}
        {items.map((item) => (
          <span key={item} className="b neu mono" style={{ paddingRight: 4 }}>
            {item}
            <button type="button" className="btn" aria-label={`Remove ${item}`} style={{ minHeight: 28, padding: '0 8px' }} onClick={() => onChange(items.filter((i) => i !== item))}>
              ×
            </button>
          </span>
        ))}
      </div>
      <form className="row" style={{ gap: 8 }} onSubmit={add}>
        <input id={id} aria-label={`Add a ${noun}`} className="in mono" style={{ flex: '1 1 220px' }} value={value} onChange={(e) => setValue(e.target.value)} />
        <button className="btn" type="submit">
          Add {noun}
        </button>
      </form>
    </div>
  )
}

export function SettingsScreen() {
  const client = useQueryClient()
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => apiFetch<Settings>('/api/settings') })
  const update = useQuery({ queryKey: ['update'], queryFn: () => apiFetch<UpdateOut>('/api/update') })
  const info = useQuery({ queryKey: ['app-info'], queryFn: () => apiFetch<AppInfo>('/api/app/info') })
  const key = useQuery({ queryKey: ['app-key'], queryFn: () => apiFetch<AppKeyOut>('/api/app-key') })
  const progress = useQuery<Progress | null>({ queryKey: ['update-progress'], queryFn: () => null, enabled: false })
  const [hidden, setHidden] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const s = settings.data
  const save = async (patch: Partial<Settings>): Promise<void> => {
    if (!s) return
    const next = { ...s, ...patch }
    client.setQueryData(['settings'], next)
    client.setQueryData(['settings'], await putJson<Settings>('/api/settings', next))
  }
  const guard: Required<GuardWatchList> = { lock_files: [], processes: [], router_ssids: [], router_processes: [], ...s?.guard }
  const saveGuard = (patch: Partial<GuardWatchList>): void => {
    if (s) void save({ guard: { ...guard, ...patch } })
  }

  const act = async (fn: () => Promise<void>): Promise<void> => {
    setMessage(null)
    try {
      await fn()
    } catch (err) {
      setMessage(err instanceof ApiError ? err.detail : String(err))
    }
  }

  const check = (): Promise<void> =>
    act(async () => {
      client.setQueryData(['update'], await postJson<UpdateOut>('/api/update/check'))
      setHidden(false)
    })

  const install = (version: string): Promise<void> =>
    act(async () => {
      try {
        await postJson('/api/update/install', { version })
      } catch (err) {
        if (err instanceof ApiError && err.status === 409 && window.confirm('Close the open terminal sessions and update?')) {
          await postJson('/api/update/install', { version, force: true })
        } else {
          throw err
        }
      }
      setMessage('Installing: OpenWrtGUI closes now and starts again when the update is done.')
    })

  const u = update.data
  const p = progress.data
  return (
    <main className="wrap">
      <div>
        <div className="eyebrow">OpenWrtGUI · this PC</div>
        <h1>Settings</h1>
      </div>
      {message && <div className="note w">{message}</div>}

      <section className="card stack" aria-labelledby="up-h">
        <div className="row">
          <h2 id="up-h">Updates</h2>
          {u && <span className="b neu mono">installed {u.current}</span>}
          <div className="spacer" />
          <div className="seg" role="group" aria-label="Update channel">
            <button type="button" className={s?.update_channel === 'stable' ? 'on' : ''} onClick={() => void save({ update_channel: 'stable' }).then(check)}>
              Stable
            </button>
            <button type="button" className={s?.update_channel === 'prerelease' ? 'on' : ''} onClick={() => void save({ update_channel: 'prerelease' }).then(check)}>
              Pre-release (CI builds)
            </button>
          </div>
          <button className="btn" type="button" onClick={() => void check()}>
            Check now
          </button>
        </div>
        <button className="tg" type="button" role="switch" aria-checked={s?.auto_check ?? false} onClick={() => void save({ auto_check: !(s?.auto_check ?? true) })}>
          <span className={s?.auto_check ? 'track on' : 'track'}>
            <span className="knob" />
          </span>
          Check at start-up and daily
        </button>
        {u?.error && <div className="note x">{u.error}</div>}
        {u && !u.available && !u.error && <div className="muted">You are up to date.</div>}
        {u?.latest && u.available && !hidden && (
          <div className="card stack" style={{ background: 'var(--surface2)' }}>
            <div className="row">
              <strong style={{ fontSize: 16 }}>{u.latest.name}</strong>
              <span className={u.latest.prerelease ? 'b park' : 'b air'}>{u.latest.prerelease ? 'CI pre-release' : 'stable'}</span>
              <span className="muted">{mb(u.latest.size)}</span>
            </div>
            {u.latest.notes && <div style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{u.latest.notes}</div>}
            <div className="row" style={{ gap: 8 }}>
              <button className="btn pri" type="button" disabled={!u.can_install} onClick={() => void install(u.latest?.version ?? '')}>
                Update now
              </button>
              <button className="btn" type="button" onClick={() => void act(async () => { client.setQueryData(['update'], await postJson<UpdateOut>('/api/update/skip', { version: u.latest?.version })) })}>
                Skip this version
              </button>
              <button className="btn" type="button" onClick={() => setHidden(true)}>
                Later
              </button>
            </div>
            {!u.can_install && <div className="muted">Updates install only in the installed app.</div>}
            {p && p.version === u.latest.version && (
              <div className="muted">
                Downloading {mb(p.done)} of {mb(p.total)}
              </div>
            )}
          </div>
        )}
        <div className="muted">
          Each download is checked against the release’s <span className="mono">SHA256SUMS.txt</span> before it runs.
          {u?.has_previous && (
            <>
              {' '}
              <button className="btn" type="button" onClick={() => void act(async () => { await postJson('/api/update/reinstall-previous') })}>
                Reinstall previous version
              </button>
            </>
          )}
        </div>
      </section>

      <div className="cards">
        <section className="card stack" aria-labelledby="ap-h">
          <h2 id="ap-h">Appearance</h2>
          <div className="seg" role="group" aria-label="Theme">
            {(['system', 'light', 'dark'] as const).map((t) => (
              <button key={t} type="button" className={s?.theme === t ? 'on' : ''} aria-pressed={s?.theme === t} onClick={() => void save({ theme: t })}>
                {t === 'system' ? 'System' : t === 'light' ? 'Light' : 'Dark'}
              </button>
            ))}
          </div>
          <div className="muted">System follows Windows (light or dark).</div>
        </section>
        <section className="card stack" aria-labelledby="fd-h">
          <h2 id="fd-h">Folders</h2>
          <dl className="kv">
            <dt>Data</dt>
            <dd className="mono">{info.data?.data_dir}</dd>
          </dl>
          <div>
            <button className="btn" type="button" onClick={() => void act(async () => { await postJson('/api/app/open-data-dir') })}>
              Open data folder
            </button>
          </div>
          <div className="note">On the bench PC the app and its data stay inside C:\Essence_SC, where SentinelOne lets them run. Updates and uninstall leave the data folder alone.</div>
        </section>
      </div>

      <section className="card stack" aria-labelledby="bg-h">
        <div className="row">
          <h2 id="bg-h">Bench Guard</h2>
          <span className="muted">while anything below is live, every router is read-only</span>
        </div>
        {s && (
          <div className="cards">
            {WATCH.map((w) => (
              <WatchGroup key={w.key} title={w.title} noun={w.noun} items={guard[w.key]} onChange={(next) => saveGuard({ [w.key]: next })} />
            ))}
          </div>
        )}
      </section>

      <div className="cards">
        <section className="card stack" aria-labelledby="key-h">
          <h2 id="key-h">App SSH key</h2>
          <dl className="kv">
            <dt>Fingerprint</dt>
            <dd className="mono">{key.data?.fingerprint}</dd>
            <dt>Key</dt>
            <dd className="mono" style={{ fontSize: 12 }}>
              {key.data?.public_line}
            </dd>
          </dl>
          <div>
            <button className="btn" type="button" onClick={() => void act(() => downloadFile('/api/app-key/public', 'openwrtgui.pub'))}>
              Export public key
            </button>
          </div>
        </section>
        <section className="card stack" aria-labelledby="al-h">
          <h2 id="al-h">Audit log</h2>
          <div className="row">
            <span className="muted">Keep</span>
            <div className="seg" role="group" aria-label="Audit log retention">
              {RETENTION.map(([days, label]) => (
                <button key={days} type="button" className={s?.audit_retention_days === days ? 'on' : ''} onClick={() => void save({ audit_retention_days: days })}>
                  {label}
                </button>
              ))}
            </div>
          </div>
        </section>
      </div>

      <section className="card row" aria-labelledby="ab-h">
        <h2 id="ab-h">About</h2>
        <span className="mono">OpenWrtGUI {info.data?.version} · GPL-3.0</span>
        <a href="https://github.com/dm17ryk/OpenWrtGUI" target="_blank" rel="noopener noreferrer">
          github.com/dm17ryk/OpenWrtGUI
        </a>
        <div className="spacer" />
        <button className="btn" type="button" onClick={() => void act(async () => { await postJson('/api/app/quit') })}>
          Quit
        </button>
      </section>
    </main>
  )
}
