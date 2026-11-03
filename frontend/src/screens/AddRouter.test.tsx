import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import { SUMMARY, sessionView } from '../testing/fixtures'
import { AddRouter } from './AddRouter'

const INSTALL = "mkdir -p /etc/dropbear && touch /etc/dropbear/authorized_keys && chmod 600 /etc/dropbear/authorized_keys && (grep -qxF 'ssh-ed25519 AAAA openwrtgui@PC' /etc/dropbear/authorized_keys || echo 'ssh-ed25519 AAAA openwrtgui@PC' >> /etc/dropbear/authorized_keys)"

const calls: Array<{ path: string; body: unknown }> = []
let installFails = false

vi.mock('../api/client', async (orig) => {
  const actual = await orig<typeof import('../api/client')>()
  const respond = async (path: string, body?: unknown): Promise<unknown> => {
    calls.push({ path, body })
    if (path === '/api/onboard') return sessionView('host_key')
    if (path.endsWith('/trust')) return sessionView('login')
    if (path.endsWith('/login')) return sessionView('install_key')
    if (path.endsWith('/install-key/preview')) return { commands: [INSTALL] }
    if (path.endsWith('/install-key')) {
      if (installFails) {
        throw new actual.ApiError(423, 'dima_night.py started 21:04 (PID 18244)', {})
      }
      return sessionView('install_key', { key_installed: true })
    }
    if (path.endsWith('/verify')) return sessionView('identify', { key_installed: true })
    if (path.endsWith('/identify')) {
      return sessionView('ports', { key_installed: true, summary: SUMMARY, proposed_port_labels: SUMMARY.port_labels })
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
  await user.type(screen.getByLabelText('Root password'), 'sim-password')
  await user.click(screen.getByRole('button', { name: 'Log in' }))
  await screen.findByRole('heading', { name: 'Install the app’s key' })
  return user
}

test('address comes from the link and the host key is shown before pinning', async () => {
  renderWizard()
  expect(screen.getByLabelText('Router address')).toHaveValue('192.168.1.4')
  await userEvent.setup().click(screen.getByRole('button', { name: 'Connect' }))
  expect(await screen.findByText('SHA256:simkey')).toBeInTheDocument()
})

test('password field is emptied after login submit', async () => {
  const user = await toLogin()
  const field = screen.getByLabelText('Root password')
  expect(field).toHaveAttribute('type', 'password')
  await user.type(field, 'sim-password')
  await user.click(screen.getByRole('button', { name: 'Log in' }))
  await screen.findByRole('heading', { name: 'Install the app’s key' })
  expect(calls.find((c) => c.path.endsWith('/login'))?.body).toEqual({ password: 'sim-password' })
  expect(screen.queryByDisplayValue('sim-password')).toBeNull()
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
