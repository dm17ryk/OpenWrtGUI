import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import type { AppInfo, Settings, UpdateOut } from '../api/types'
import { SettingsScreen } from './Settings'

const puts: Array<{ path: string; body: Settings }> = []

vi.mock('../api/client', async (orig) => {
  const actual = await orig<typeof import('../api/client')>()
  return {
    ...actual,
    putJson: vi.fn(async (path: string, body: Settings) => {
      puts.push({ path, body })
      return body
    }),
    postJson: vi.fn(async () => ({})),
    apiFetch: vi.fn(async () => {
      throw new Error('should be cached')
    }),
  }
})

const SETTINGS: Settings = {
  theme: 'system',
  update_channel: 'stable',
  auto_check: true,
  skipped_version: null,
  last_check: null,
  audit_retention_days: 90,
  guard: { lock_files: [], processes: ['dima_night.py'], router_ssids: ['OpenWrtB'], router_processes: [] },
}

const UPDATE: UpdateOut = {
  current: '0.1.0-dev',
  channel: 'stable',
  latest: { version: '0.1.0', name: 'OpenWrtGUI 0.1.0', notes: 'First release.', prerelease: false, published_at: null, size: 48200000 },
  available: true,
  last_check: null,
  error: null,
  can_install: false,
  has_previous: false,
}

const INFO: AppInfo = { version: '0.1.0-dev', mode: 'simulator', data_dir: 'C:\\Essence_SC\\apps\\OpenWrtGUI-data', can_install: false }

beforeEach(() => {
  puts.length = 0
})

function renderSettings(update: UpdateOut = UPDATE) {
  const client = new QueryClient()
  client.setQueryData(['settings'], SETTINGS)
  client.setQueryData(['update'], update)
  client.setQueryData(['app-info'], INFO)
  client.setQueryData(['app-key'], { public_line: 'ssh-ed25519 AAAA openwrtgui@PC', fingerprint: 'SHA256:appkey' })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SettingsScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('theme change PUTs settings', async () => {
  renderSettings()
  const group = screen.getByRole('group', { name: 'Theme' })
  await userEvent.setup().click(within(group).getByRole('button', { name: 'Dark' }))
  expect(puts.at(-1)?.body.theme).toBe('dark')
})

test('watch list add and remove', async () => {
  const user = userEvent.setup()
  renderSettings()
  const field = screen.getByLabelText('Add a process')
  await user.type(field, 'txlab_*.py')
  await user.click(screen.getByRole('button', { name: 'Add process' }))
  expect(puts.at(-1)?.body.guard?.processes).toEqual(['dima_night.py', 'txlab_*.py'])
  await user.type(field, 'dima_night.py')
  await user.click(screen.getByRole('button', { name: 'Add process' }))
  expect(puts).toHaveLength(1)
  await user.click(screen.getByRole('button', { name: 'Remove dima_night.py' }))
  expect(puts.at(-1)?.body.guard?.processes).toEqual(['txlab_*.py'])
})

test('update offer renders and dev build cannot install', () => {
  renderSettings()
  const updates = screen.getByRole('region', { name: 'Updates' })
  expect(within(updates).getByText('OpenWrtGUI 0.1.0')).toBeInTheDocument()
  expect(within(updates).getByText('Updates install only in the installed app.')).toBeInTheDocument()
  expect(within(updates).getByRole('button', { name: 'Update now' })).toBeDisabled()
})

test('folders, key and retention are shown', async () => {
  renderSettings()
  expect(screen.getByText('C:\\Essence_SC\\apps\\OpenWrtGUI-data')).toBeInTheDocument()
  expect(screen.getByText('SHA256:appkey')).toBeInTheDocument()
  await userEvent.setup().click(screen.getByRole('button', { name: '1 year' }))
  expect(puts.at(-1)?.body.audit_retention_days).toBe(365)
})

test('update status says when no check has run yet', () => {
  renderSettings({ ...UPDATE, latest: null, available: false })
  const updates = screen.getByRole('region', { name: 'Updates' })
  expect(within(updates).getByText('Not checked yet.')).toBeInTheDocument()
  expect(within(updates).queryByText(/up to date/)).toBeNull()
})

test('update status names the last check when up to date', () => {
  renderSettings({ ...UPDATE, latest: null, available: false, last_check: '2026-11-04T09:30:00Z' })
  const updates = screen.getByRole('region', { name: 'Updates' })
  expect(within(updates).getByText(/^You are up to date \(checked .+\)\.$/)).toBeInTheDocument()
})
