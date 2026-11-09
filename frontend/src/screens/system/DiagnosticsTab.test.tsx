import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import type { GuardOut } from '../../api/types'
import { AP2_PING } from '../../testing/system'
import { DiagnosticsTab } from './DiagnosticsTab'

const calls: Array<{ path: string; body: unknown }> = []

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body?: unknown) => {
      calls.push({ path, body })
      if (path !== '/api/routers/ap2/system/diagnose') throw new Error(`unexpected ${path}`)
      return AP2_PING
    }),
  }
})

const CLEAR: GuardOut = { live: false, reasons: [], checked_at: '2026-11-09T12:00:00' }
const LIVE = { live: true, reasons: [{ kind: 'process', text: 'TXCTL v14 night run', detail: 'pytest' }], checked_at: '2026-11-09T12:00:00' } as GuardOut

beforeEach(() => {
  calls.length = 0
})

function renderTab(guard: GuardOut = CLEAR) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['guard'], guard)
  render(
    <QueryClientProvider client={client}>
      <DiagnosticsTab routerId="ap2" />
    </QueryClientProvider>,
  )
}

test('a ping prints its replies under the exact command', async () => {
  const user = userEvent.setup()
  renderTab()
  await user.type(screen.getByRole('textbox', { name: 'Target' }), '192.168.1.10')
  await user.click(screen.getByRole('button', { name: 'Run' }))
  expect(calls).toEqual([{ path: '/api/routers/ap2/system/diagnose', body: { tool: 'ping', target: '192.168.1.10' } }])
  const out = await screen.findByRole('log', { name: 'Diagnostic output' })
  expect(within(out).getByText("$ timeout -s KILL 25 ping -c 4 -W 2 '192.168.1.10'")).toBeInTheDocument()
  expect(out).toHaveTextContent('4 packets transmitted, 4 packets received, 0% loss')
  expect(screen.getByRole('button', { name: 'Help: Diagnostics' })).toBeInTheDocument()
})

test('the tool is picked before Run', async () => {
  const user = userEvent.setup()
  renderTab()
  await user.click(screen.getByRole('button', { name: 'Traceroute' }))
  await user.type(screen.getByRole('textbox', { name: 'Target' }), 'openwrt.org')
  await user.click(screen.getByRole('button', { name: 'Run' }))
  expect(calls[0].body).toEqual({ tool: 'traceroute', target: 'openwrt.org' })
})

test('during a run Run is disabled with the run named', () => {
  renderTab(LIVE)
  expect(screen.getByRole('button', { name: 'Run' })).toBeDisabled()
  expect(screen.getByText(/TXCTL v14 night run/)).toBeInTheDocument()
})
