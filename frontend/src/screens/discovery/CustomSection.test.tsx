import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import type { GuardOut, ToolCard } from '../../api/types'
import { AP1_DISCOVERY, HELP_PLAN, PORTCTL_CARD } from '../../testing/discovery'
import { CustomSection } from './CustomSection'

const CLEAR: GuardOut = { live: false, reasons: [], checked_at: '2026-11-08T12:00:00' }
const LIVE: GuardOut = {
  live: true,
  reasons: [{ kind: 'process', detail: 'dima_night.py', pid: 18244, router: null, since: '21:04', text: 'dima_night.py started 21:04 (PID 18244)' }],
  checked_at: '2026-11-08T21:05:00',
}
const TOOLS = '/api/tools/dlink%2Cdwr-921-c3-uboot'
const calls: Array<{ path: string; body?: unknown }> = []
let guard: GuardOut = CLEAR
let cards: ToolCard[] = []

function plan(lines: string[], digest: string) {
  return { router_id: 'ap1', screen: 'Discovery', lines, warnings: [], rollback: false, target_host: null, digest }
}

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  const respond = async (path: string, body?: unknown): Promise<unknown> => {
    calls.push({ path, body })
    const b = (body ?? {}) as { label?: string; values?: Record<string, string>; action?: string; name?: string }
    if (path === '/api/guard') return guard
    if (path === TOOLS) return cards
    if (path === '/api/routers/ap1/discovery/help/preview') return HELP_PLAN
    if (path === '/api/routers/ap1/discovery/help/apply') return { output: 'wifi-mirror 1.0: mirrors the bench SSID\n', exit_status: 0 }
    if (path === '/api/routers/ap1/discovery/tool/preview') {
      return plan([`/usr/sbin/dwr921-portctl ${b.label} ${b.values?.arg1 ?? ''}`], 't1')
    }
    if (path === '/api/routers/ap1/discovery/tool/apply') return { output: 'lan2: enabled\n', exit_status: 0 }
    if (path === '/api/routers/ap1/discovery/service/preview') return plan([`/etc/init.d/${b.name} ${b.action}`], `s-${b.action}`)
    if (path === '/api/routers/ap1/discovery/service/apply') {
      const running = b.action !== 'stop'
      return {
        router_id: 'ap1',
        applied: true,
        verified: true,
        checks: [{ name: `service ${b.name}`, ok: true, detail: running ? 'running' : 'not running' }],
        error: null,
        host: '192.168.1.1',
      }
    }
    throw new Error(`unexpected ${path}`)
  }
  return {
    ...actual,
    apiFetch: vi.fn((path: string) => respond(path)),
    postJson: vi.fn((path: string, body?: unknown) => respond(path, body ?? {})),
  }
})

beforeEach(() => {
  calls.length = 0
  guard = CLEAR
  cards = []
})

function renderCustom() {
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <CustomSection routerId="ap1" state={AP1_DISCOVERY} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return user
}

function programRow(path: string): HTMLElement {
  return screen.getByText(path).closest('li') as HTMLElement
}

function serviceRow(name: string): HTMLElement {
  return within(screen.getByRole('table', { name: 'Custom services' })).getByText(name).closest('tr') as HTMLElement
}

test('shows portctl as a card linking to Ports', () => {
  renderCustom()
  expect(screen.getByRole('link', { name: 'Ports screen' })).toHaveAttribute('href', '/routers/ap1/ports')
  expect(screen.getByText('Usage: dwr921-portctl {port-status|port-enable|port-disable} {lan1|lan2|lan3|lan4|wan}').tagName).toBe('PRE')
})

test('runs --help through the preview and shows the output', async () => {
  const user = renderCustom()
  await user.click(within(programRow('/usr/sbin/wifi-mirror')).getByRole('button', { name: 'Run --help' }))
  expect(await screen.findByText(HELP_PLAN.warnings[0])).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Run' }))
  const output = await screen.findByText('wifi-mirror 1.0: mirrors the bench SSID')
  expect(output.tagName).toBe('PRE')
  const applied = calls.find((c) => c.path.endsWith('/help/apply'))
  expect(applied?.body).toEqual({ path: '/usr/sbin/wifi-mirror', digest: HELP_PLAN.digest })
})

test('runs a promoted write command with its parameter', async () => {
  cards = [PORTCTL_CARD]
  const user = renderCustom()
  const card = await screen.findByRole('region', { name: 'Card dwr921-portctl' })
  await user.click(within(card).getByRole('button', { name: 'port-enable' }))
  await user.selectOptions(within(card).getByLabelText('arg1'), 'lan2')
  expect(await within(card).findByRole('region', { name: 'Command preview' })).toHaveTextContent('/usr/sbin/dwr921-portctl port-enable lan2')
  await user.click(within(card).getByRole('button', { name: 'Run' }))
  expect(await within(card).findByText('lan2: enabled')).toBeVisible()
  const applied = calls.find((c) => c.path.endsWith('/tool/apply'))
  expect(applied?.body).toEqual({ path: '/usr/sbin/dwr921-portctl', label: 'port-enable', values: { arg1: 'lan2' }, digest: 't1' })
})

test('stops and starts a custom service', async () => {
  const user = renderCustom()
  expect(within(serviceRow('wifi-mirror')).getByText('running')).toBeVisible()
  await user.click(within(serviceRow('wifi-mirror')).getByRole('button', { name: 'Stop' }))
  expect(await screen.findByRole('region', { name: 'Command preview' })).toHaveTextContent('/etc/init.d/wifi-mirror stop')
  await user.click(screen.getByRole('button', { name: 'Apply' }))
  expect(await within(serviceRow('wifi-mirror')).findByText('stopped')).toBeVisible()
  await user.click(within(serviceRow('wifi-mirror')).getByRole('button', { name: 'Start' }))
  expect(await screen.findByRole('region', { name: 'Command preview' })).toHaveTextContent('/etc/init.d/wifi-mirror start')
  await user.click(screen.getByRole('button', { name: 'Apply' }))
  expect(await within(serviceRow('wifi-mirror')).findByText('running')).toBeVisible()
  const applied = calls.filter((c) => c.path.endsWith('/service/apply')).map((c) => c.body)
  expect(applied).toEqual([
    { name: 'wifi-mirror', action: 'stop', digest: 's-stop' },
    { name: 'wifi-mirror', action: 'start', digest: 's-start' },
  ])
})

test('greys writes and every card command while Bench Guard is live', async () => {
  guard = LIVE
  cards = [{ ...PORTCTL_CARD, commands: PORTCTL_CARD.commands.map((c) => (c.label === 'port-status' ? { ...c, write: false } : c)) }]
  renderCustom()
  expect(await screen.findByText(/dima_night\.py started 21:04/)).toBeVisible()
  const help = within(programRow('/usr/sbin/wifi-mirror')).getByRole('button', { name: 'Run --help' })
  await waitFor(() => expect(help).toBeDisabled())
  expect(help).toHaveAttribute('title', expect.stringContaining('dima_night.py'))
  expect(within(serviceRow('wifi-mirror')).getByRole('button', { name: 'Stop' })).toBeDisabled()
  const card = await screen.findByRole('region', { name: 'Card dwr921-portctl' })
  expect(within(card).getByRole('button', { name: 'port-enable' })).toBeDisabled()
  // marked read-only, but a custom program cannot be checked as a read: it waits too
  expect(within(card).getByRole('button', { name: 'port-status' })).toBeDisabled()
})
