import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { apiFetch } from '../../api/client'
import { AP2_KERNEL, AP2_PROCESSES, AP2_SYSLOG } from '../../testing/system'
import { LogsTab } from './LogsTab'
import { ProcessesTab } from './ProcessesTab'

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (String(path).startsWith('/api/routers/ap2/system/logs?kind=system')) return AP2_SYSLOG
      if (String(path).startsWith('/api/routers/ap2/system/logs?kind=kernel')) return AP2_KERNEL
      if (path === '/api/routers/ap2/system/processes') return AP2_PROCESSES
      throw new Error(`unexpected ${path}`)
    }),
  }
})

const fetched = (): string[] => vi.mocked(apiFetch).mock.calls.map((c) => c[0])

beforeEach(() => {
  vi.mocked(apiFetch).mockClear()
})
afterEach(() => vi.useRealTimers())

function renderTab(ui: React.ReactElement) {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)
}

test('the system log lists its lines; the text filter hides the others', async () => {
  const user = userEvent.setup()
  renderTab(<LogsTab routerId="ap2" />)
  const log = await screen.findByRole('log', { name: 'System log' })
  expect(within(log).getAllByRole('listitem')).toHaveLength(AP2_SYSLOG.length)
  await user.type(screen.getByRole('textbox', { name: 'Filter' }), 'lte')
  const kept = within(log).getAllByRole('listitem')
  expect(kept.map((li) => li.textContent)).toEqual([
    expect.stringContaining("Interface 'lte' is now up"),
    expect.stringContaining('internet up via lte'),
  ])
  expect(fetched()).toContain('/api/routers/ap2/system/logs?kind=system&lines=100')
  expect(screen.getByRole('button', { name: 'Help: Logs' })).toBeInTheDocument()
})

test('the level filter keeps that level and the more severe ones', async () => {
  const user = userEvent.setup()
  renderTab(<LogsTab routerId="ap2" />)
  const log = await screen.findByRole('log', { name: 'System log' })
  await user.selectOptions(screen.getByRole('combobox', { name: 'Level' }), 'warning')
  const kept = within(log).getAllByRole('listitem')
  expect(kept).toHaveLength(2) // one err, one warn
})

test('the kernel log and the length are picked; Follow reads again every 5 s', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  renderTab(<LogsTab routerId="ap2" />)
  await screen.findByRole('log', { name: 'System log' })
  await user.click(screen.getByRole('button', { name: 'Kernel' }))
  await user.selectOptions(screen.getByRole('combobox', { name: 'Lines' }), '500')
  expect(await screen.findByRole('log', { name: 'Kernel log' })).toHaveTextContent('qmi_wwan')
  expect(fetched()).toContain('/api/routers/ap2/system/logs?kind=kernel&lines=500')
  const before = fetched().length
  await user.click(screen.getByRole('checkbox', { name: 'Follow' }))
  await vi.advanceTimersByTimeAsync(5100)
  await waitFor(() => expect(fetched().length).toBeGreaterThan(before))
})

test('processes are sorted by CPU and by another column on its heading', async () => {
  const user = userEvent.setup()
  renderTab(<ProcessesTab routerId="ap2" />)
  const table = await screen.findByRole('table', { name: 'Processes' })
  const firstCommand = (): string => within(within(table).getAllByRole('row')[1]).getAllByRole('cell').at(-1)?.textContent ?? ''
  const top = [...AP2_PROCESSES.rows].sort((a, b) => b.cpu_pct - a.cpu_pct)[0]
  expect(firstCommand()).toBe(top.command)
  expect(within(table).getByRole('columnheader', { name: /RSS/ })).toBeInTheDocument()
  await user.click(within(table).getByRole('button', { name: 'PID' }))
  const lowest = [...AP2_PROCESSES.rows].sort((a, b) => a.pid - b.pid)[0]
  expect(firstCommand()).toBe(lowest.command)
})
