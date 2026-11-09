import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import type { GuardOut } from '../../api/types'
import { LTE_CONNECT_NO_ADDRESS, LTE_CONNECT_PLAN, LTE_REBOOT_PLAN } from '../../testing/lte'
import { ActionsCard } from './ActionsCard'

const calls: Array<{ path: string; body: unknown }> = []
let refuse: { status: number; detail: string } | null = null

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body?: unknown) => {
      calls.push({ path, body })
      const action = (body as { action: string }).action
      if (path === '/api/routers/ap2/lte/action/preview') return action === 'reboot' ? LTE_REBOOT_PLAN : LTE_CONNECT_PLAN
      if (path === '/api/routers/ap2/lte/action/apply') {
        if (refuse) throw new actual.ApiError(refuse.status, refuse.detail, {})
        return LTE_CONNECT_NO_ADDRESS
      }
      throw new Error(`unexpected ${path}`)
    }),
  }
})

const CLEAR: GuardOut = { live: false, reasons: [], checked_at: '2026-11-08T12:00:00' }
const LIVE: GuardOut = {
  live: true,
  reasons: [{ kind: 'process', text: 'TXCTL v14 night run', detail: 'pytest' }],
  checked_at: '2026-11-08T12:00:00',
} as GuardOut

beforeEach(() => {
  calls.length = 0
  refuse = null
})

function renderActions(guard: GuardOut = CLEAR) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['guard'], guard)
  render(
    <QueryClientProvider client={client}>
      <ActionsCard routerId="ap2" routerName="AP2 · office" onDone={() => {}} />
    </QueryClientProvider>,
  )
  return screen.getByRole('group', { name: 'LTE action' })
}

test('Reboot modem previews the four uqmi lines and ifup lte', async () => {
  const user = userEvent.setup()
  const actions = renderActions()
  await user.click(within(actions).getByRole('button', { name: 'Reboot modem' }))
  const preview = await screen.findByRole('region', { name: 'Command preview' })
  for (const line of LTE_REBOOT_PLAN.lines) expect(preview).toHaveTextContent(line)
  expect(LTE_REBOOT_PLAN.lines.filter((l) => l.startsWith('uqmi '))).toHaveLength(4)
  expect(calls.at(-1)).toEqual({ path: '/api/routers/ap2/lte/action/preview', body: { action: 'reboot' } })
  expect(screen.getByText(LTE_REBOOT_PLAN.warnings[0])).toBeInTheDocument()
  expect(screen.getByText(/Reset to factory defaults is not offered yet \(open item O1\)/)).toBeInTheDocument()
})

test('a connect without an address yet is a note, not a failure', async () => {
  const user = userEvent.setup()
  const actions = renderActions()
  await user.click(within(actions).getByRole('button', { name: 'Connect' }))
  await screen.findByRole('region', { name: 'Command preview' })
  await user.click(screen.getByRole('button', { name: 'Run: Connect' }))
  expect(calls.at(-1)).toEqual({ path: '/api/routers/ap2/lte/action/apply', body: { action: 'connect', digest: LTE_CONNECT_PLAN.digest } })
  const result = await screen.findByRole('status', { name: 'Apply result' })
  expect(result).toHaveTextContent('Applied and checked')
  expect(screen.getByText("No address yet: waiting for the carrier's DHCP. The session is up; the address follows.")).toBeInTheDocument()
})

test('a 423 shows the run', async () => {
  const user = userEvent.setup()
  refuse = { status: 423, detail: 'TXCTL v14 night run' }
  const actions = renderActions()
  await user.click(within(actions).getByRole('button', { name: 'Disconnect' }))
  await screen.findByRole('region', { name: 'Command preview' })
  await user.click(screen.getByRole('button', { name: 'Run: Disconnect' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('TXCTL v14 night run')
})

test('the actions wait while a harness run is live', () => {
  const actions = renderActions(LIVE)
  for (const name of ['Connect', 'Disconnect', 'Reboot modem']) {
    expect(within(actions).getByRole('button', { name })).toBeDisabled()
  }
  expect(screen.getByText(/A harness run is live \(TXCTL v14 night run\)/)).toBeInTheDocument()
})
