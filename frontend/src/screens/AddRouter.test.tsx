import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { RouterItem, SessionView } from '../api/types'
import { AP1, SUMMARY, sessionView } from '../testing/fixtures'
import { AddRouter } from './AddRouter'

const INSTALL = "mkdir -p /etc/dropbear && touch /etc/dropbear/authorized_keys && chmod 600 /etc/dropbear/authorized_keys && (grep -qxF 'ssh-ed25519 AAAA openwrtgui@PC' /etc/dropbear/authorized_keys || echo 'ssh-ed25519 AAAA openwrtgui@PC' >> /etc/dropbear/authorized_keys)"

const PC_KEY = 'C:\\Essence_SC\\home\\.ssh\\id_rsa'

const calls: Array<{ path: string; body: unknown }> = []
let installFails = false
let autoLogin: SessionView = sessionView('login')
let autoLoginFails = false
let hostKey: SessionView = sessionView('host_key')
const REFLASHED: RouterItem = {
  ...AP1,
  record: { ...AP1.record, host: '192.168.1.4', reflashed: { board: 'dlink,dwr-921-c3-uboot', revision: 'r35700-0c0ffee000', at: '2026-11-08T12:00:00' } },
}

vi.mock('../api/client', async (orig) => {
  const actual = await orig<typeof import('../api/client')>()
  const respond = async (path: string, body?: unknown): Promise<unknown> => {
    calls.push({ path, body })
    if (path === '/api/onboard') return hostKey
    if (path === '/api/routers') return [REFLASHED]
    if (path.endsWith('/trust')) return sessionView('login')
    if (path.endsWith('/auto-login')) {
      if (autoLoginFails) throw new actual.ApiError(504, '192.168.1.4:22: timed out', {})
      return autoLogin
    }
    if (path.endsWith('/login')) return sessionView('install_key', { login_method: 'password' })
    if (path.endsWith('/install-key/preview')) return { commands: [INSTALL] }
    if (path.endsWith('/install-key')) {
      if (installFails) {
        throw new actual.ApiError(423, 'dima_night.py started 21:04 (PID 18244)', {})
      }
      return sessionView('install_key', { key_installed: true })
    }
    if (path.endsWith('/verify')) return sessionView('identify', { key_installed: true })
    if (path.endsWith('/identify')) {
      const after = autoLogin.step === 'identify' ? autoLogin : sessionView('identify', { key_installed: true })
      return { ...after, step: 'ports', summary: SUMMARY, proposed_port_labels: SUMMARY.port_labels }
    }
    if (path.endsWith('/finish')) return { id: 'ap4' }
    throw new Error(`unexpected ${path}`)
  }
  return {
    ...actual,
    apiFetch: vi.fn((path: string) => respond(path)),
    postJson: vi.fn((path: string, body?: unknown) => respond(path, body)),
  }
})

beforeEach(() => {
  calls.length = 0
  installFails = false
  autoLogin = sessionView('login')
  autoLoginFails = false
  hostKey = sessionView('host_key')
})

function renderWizard() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={['/add?host=192.168.1.4']}>
        <AddRouter />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function toLogin() {
  const user = userEvent.setup()
  renderWizard()
  await user.click(screen.getByRole('button', { name: 'Connect' }))
  await user.click(await screen.findByRole('button', { name: 'Accept and pin' }))
  return user
}

async function toInstall() {
  const user = await toLogin()
  await user.type(await screen.findByLabelText('Password'), 'sim-password')
  await user.click(screen.getByRole('button', { name: 'Log in' }))
  await screen.findByRole('heading', { name: 'Install the app’s key' })
  return user
}

test('address comes from the link and the host key is shown before pinning', async () => {
  renderWizard()
  expect(screen.getByLabelText('Router address')).toHaveValue('192.168.1.4')
  expect(screen.getByRole('button', { name: 'Help: 1. Where is the router?' })).toBeInTheDocument()
  await userEvent.setup().click(screen.getByRole('button', { name: 'Connect' }))
  expect(await screen.findByText('SHA256:simkey')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Help: 2. Check the router is the one you mean' })).toBeInTheDocument()
})

test('expects the new host key after a matching reflash', async () => {
  hostKey = sessionView('host_key', { changed_from: 'SHA256:old', expected_reflash: true })
  renderWizard()
  await userEvent.setup().click(screen.getByRole('button', { name: 'Connect' }))
  expect(await screen.findByText('Expected after the flash: dlink,dwr-921-c3-uboot r35700-0c0ffee000')).toBeVisible()
  expect(screen.queryByText(/may not be talking to your router/)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Accept and pin' })).toBeEnabled()
})

test('a changed key without a matching reflash keeps the warning', async () => {
  hostKey = sessionView('host_key', { changed_from: 'SHA256:old' })
  renderWizard()
  await userEvent.setup().click(screen.getByRole('button', { name: 'Connect' }))
  expect(await screen.findByText(/may not be talking to your router/)).toBeVisible()
  expect(screen.queryByText(/Expected after the flash/)).not.toBeInTheDocument()
})

test('the install and skip buttons explain themselves from the manual', async () => {
  const user = await toInstall()
  await user.hover(screen.getByRole('button', { name: 'Install key' }))
  expect(await screen.findByRole('tooltip')).toHaveTextContent('The wizard shows the exact command it will run')
  await user.unhover(screen.getByRole('button', { name: 'Install key' }))
  await user.hover(screen.getByRole('button', { name: 'Skip for now' }))
  expect(await screen.findByText(/shows needs app key on the dashboard/)).toBeInTheDocument()
})

test('after pinning it tries the logins by itself, then asks', async () => {
  await toLogin()
  expect(await screen.findByText(/None of them worked/)).toHaveTextContent('the app’s key, this PC’s keys and root / root')
  expect(calls.map((c) => c.path)).toContain('/api/onboard/s1/auto-login')
  expect(screen.getByLabelText('User')).toHaveValue('root')
})

test('when the automatic login fails it says so and can try again', async () => {
  autoLoginFails = true
  const user = await toLogin()
  expect(await screen.findByRole('alert')).toHaveTextContent('192.168.1.4:22: timed out')
  expect(screen.getByText(/The automatic login stopped/)).toBeInTheDocument()
  expect(screen.queryByText(/None of them worked/)).toBeNull()
  autoLoginFails = false
  await user.click(screen.getByRole('button', { name: 'Try again' }))
  expect(await screen.findByText(/None of them worked/)).toBeInTheDocument()
  expect(calls.filter((c) => c.path.endsWith('/auto-login'))).toHaveLength(2)
})

test('password field is emptied after login submit and the user goes along', async () => {
  const user = await toLogin()
  const field = await screen.findByLabelText('Password')
  expect(field).toHaveAttribute('type', 'password')
  await user.type(field, 'sim-password')
  await user.click(screen.getByRole('button', { name: 'Log in' }))
  await screen.findByRole('heading', { name: 'Install the app’s key' })
  expect(calls.find((c) => c.path.endsWith('/login'))?.body).toEqual({ password: 'sim-password', username: 'root' })
  expect(screen.queryByDisplayValue('sim-password')).toBeNull()
})

test('a key this PC already has goes straight to identify and installs nothing', async () => {
  autoLogin = sessionView('identify', { login_method: 'pc_key', key_path: PC_KEY })
  await toLogin()
  expect(await screen.findByRole('heading', { name: 'What is this router?' })).toBeInTheDocument()
  expect(screen.getByText(`this PC’s key ${PC_KEY} already works; the app uses it and installed nothing`)).toBeInTheDocument()
  expect(calls.some((c) => c.path.includes('/install-key'))).toBe(false)
})

test('the app key already on the router goes straight to identify', async () => {
  autoLogin = sessionView('identify', { login_method: 'app_key', key_installed: true })
  await toLogin()
  expect(await screen.findByText('the app key was already on the router and works')).toBeInTheDocument()
})

test('root / root lands on the install step with a note', async () => {
  autoLogin = sessionView('install_key', { login_method: 'default_password' })
  await toLogin()
  await screen.findByRole('heading', { name: 'Install the app’s key' })
  expect(screen.getByText(/Logged in with the default root \/ root/)).toBeInTheDocument()
  expect(await screen.findByText(INSTALL)).toBeInTheDocument()
})

test('install step shows the exact preview command from the API', async () => {
  await toInstall()
  expect(await screen.findByText(INSTALL)).toBeInTheDocument()
})

test('423 during install shows the guard reason', async () => {
  installFails = true
  const user = await toInstall()
  await user.click(screen.getByRole('button', { name: 'Install key' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('dima_night.py started 21:04 (PID 18244)')
})

test('port map prefilled LAN4 for internal port 0 and editable', async () => {
  const user = await toInstall()
  await user.click(screen.getByRole('button', { name: 'Install key' }))
  await user.click(await screen.findByRole('button', { name: 'Continue' }))
  const field = await screen.findByLabelText('Label for internal port 0')
  expect(field).toHaveValue('LAN4')
  await user.clear(field)
  await user.type(field, 'Panel ETH')
  await user.type(screen.getByLabelText('Name'), 'AP4 · test')
  await user.click(screen.getByRole('button', { name: 'Save port map' }))
  const finish = calls.find((c) => c.path.endsWith('/finish'))
  expect(finish?.body).toEqual(expect.objectContaining({ name: 'AP4 · test', port_labels: expect.objectContaining({ '0': 'Panel ETH' }) }))
})

test('ApiError is exported for screens', () => {
  expect(new ApiError(403, 'x', null).status).toBe(403)
})
