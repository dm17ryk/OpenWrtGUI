import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { ApiError, postJson } from '../api/client'
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
  known_devices: [],
  known_tables: [
    { match: 'inet fw4 chain BENCHSIPGUARD', owner: 'dima_night', depends: 'dima_night expects BENCHSIPGUARD.' },
    { match: 'bridge voipdscp', owner: 'voip_chain', depends: 'VoIP chain runs expect RTP and SIP marked EF.' },
  ],
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

test('asks before stopping live operations', async () => {
  const user = userEvent.setup()
  const busy = {
    detail: 'Live work is running',
    open_terminals: 1,
    live: ['Step-through on AP2 radio0', 'Capture on AP2 br-lan'],
  }
  vi.mocked(postJson).mockRejectedValueOnce(new ApiError(409, busy.detail, busy))
  const asked = vi.spyOn(window, 'confirm').mockReturnValue(true)
  renderSettings({ ...UPDATE, can_install: true })
  await user.click(within(screen.getByRole('region', { name: 'Updates' })).getByRole('button', { name: 'Update now' }))
  expect(asked).toHaveBeenCalledWith(
    'Stop the step-through on AP2 radio0 (its radio is restored first) and the capture on AP2 br-lan, ' +
      'close 1 terminal, then update?',
  )
  expect(vi.mocked(postJson)).toHaveBeenLastCalledWith('/api/update/install', { version: '0.1.0', force: true })
  asked.mockRestore()
})

test('reinstalling the previous version asks the same question', async () => {
  const user = userEvent.setup()
  const busy = { detail: 'Live work is running', open_terminals: 0, live: ['Capture on AP2 mon0'] }
  vi.mocked(postJson).mockRejectedValueOnce(new ApiError(409, busy.detail, busy))
  const asked = vi.spyOn(window, 'confirm').mockReturnValue(true)
  renderSettings({ ...UPDATE, has_previous: true })
  await user.click(within(screen.getByRole('region', { name: 'Updates' })).getByRole('button', { name: 'Reinstall previous version' }))
  expect(asked).toHaveBeenCalledWith('Stop the capture on AP2 mon0, then update?')
  expect(vi.mocked(postJson)).toHaveBeenLastCalledWith('/api/update/reinstall-previous', { force: true })
  asked.mockRestore()
})

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

test('every settings section offers help, and the update buttons explain themselves', async () => {
  renderSettings()
  for (const name of ['Settings', 'Updates', 'Appearance', 'Folders', 'Bench Guard', 'App SSH key', 'Audit log', 'About']) {
    expect(screen.getByRole('button', { name: `Help: ${name}` })).toBeInTheDocument()
  }
  await userEvent.setup().hover(screen.getByRole('button', { name: 'Check now' }))
  expect(await screen.findByRole('tooltip')).toHaveTextContent('At start-up and once a day')
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

test('Known devices adds a name with its MACs, and Known tables lists the harness tables', async () => {
  const user = userEvent.setup()
  renderSettings()
  const card = screen.getByRole('region', { name: 'Known devices' })
  await user.type(within(card).getByLabelText('Device name'), 'panel')
  await user.type(within(card).getByLabelText('MAC addresses'), 'F4:12:FA:F3:57:68, e4:5f:01:aa:bb:01')
  await user.click(within(card).getByRole('button', { name: 'Add device' }))
  expect(puts.at(-1)?.body.known_devices).toEqual([{ name: 'panel', macs: ['f4:12:fa:f3:57:68', 'e4:5f:01:aa:bb:01'] }])
  expect(within(card).getByText('panel')).toBeInTheDocument()
  const tables = screen.getByRole('region', { name: 'Known tables' })
  expect(within(tables).getByText('bridge voipdscp')).toBeInTheDocument()
  expect(within(tables).getByText('voip_chain')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Help: Known devices' })).toBeInTheDocument()
})
