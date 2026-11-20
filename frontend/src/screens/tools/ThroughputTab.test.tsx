import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { ToolSessionView } from '../../api/types'
import { ThroughputTab } from './ThroughputTab'

const CMD = 'echo "OWG-PID $$"; exec timeout -s KILL 25 iperf3 -c 192.168.1.10 -p 5201 -t 10 -J --json-stream --forceflush 2>&1'
const CPU = "iperf3 runs on the router's CPU: on a small router the result is often the CPU's limit, not the link's."
const HINT = 'From your PC: iperf3 -c 192.168.1.1 -p 5201. The router waits up to 5 minutes for one test.'
const HOST_TEXT = 'A host is an IPv4 address or a name: letters, digits, dots and dashes.'

const posts: Array<[string, unknown]> = []
let sessions: ToolSessionView[] = []
let startError: ApiError | null = null

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path === '/api/routers/ap1/tools/sessions') return sessions
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body: unknown) => {
      posts.push([path, body])
      const b = (body ?? {}) as { mode?: string; host?: string }
      if (path.endsWith('/throughput/preview')) {
        if (b.host === 'x; reboot') throw new actual.ApiError(422, HOST_TEXT, { detail: HOST_TEXT })
        return b.mode === 'server'
          ? { lines: ['iperf3 -s -1'], warnings: [CPU, HINT], digest: 's1' }
          : { lines: [CMD], warnings: [CPU], digest: 'd1' }
      }
      if (path.endsWith('/throughput/start')) {
        if (startError) throw startError
        return session({ running: true })
      }
      if (path.endsWith('/stop')) return session({ running: false })
      throw new Error(`unexpected ${path}`)
    }),
  }
})

function session(over: Partial<ToolSessionView> = {}): ToolSessionView {
  return {
    id: 's1',
    router_id: 'ap1',
    kind: 'throughput',
    title: 'Throughput',
    command: CMD,
    started_at: 1000,
    ends_at: 1025,
    running: false,
    intervals: [{ start_s: 0, end_s: 1, mbps: 94.2, retransmits: 0, jitter_ms: null, lost_pct: null }],
    summary: { sent_mbps: 95.0, received_mbps: 94.0, retransmits: 3, jitter_ms: null, lost_pct: null, cpu_pct: 42.2 },
    peers: [],
    notes: [],
    error: null,
    ...over,
  }
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  posts.length = 0
  sessions = []
  startError = null
})

afterEach(() => {
  vi.useRealTimers()
})

function show() {
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ThroughputTab routerId="ap1" />
    </QueryClientProvider>,
  )
  return user
}

test('the fields, with the UDP rate only for UDP', async () => {
  const user = show()
  const mode = screen.getByLabelText('The router')
  expect(within(mode).getAllByRole('option').map((o) => o.textContent)).toEqual(['connects to a host', 'waits for a client'])
  for (const label of ['Host', 'Port', 'Protocol', 'Direction', 'Duration (s)']) {
    expect(screen.getByLabelText(label)).toBeInTheDocument()
  }
  const direction = screen.getByLabelText('Direction')
  expect(within(direction).getAllByRole('option').map((o) => o.textContent)).toEqual(['Router sends', 'Router receives'])
  expect(screen.queryByLabelText('UDP rate (Mb/s)')).toBeNull()
  await user.selectOptions(screen.getByLabelText('Protocol'), 'udp')
  expect(screen.getByLabelText('UDP rate (Mb/s)')).toBeInTheDocument()
})

test('the preview shows the exact line and the CPU warning; Start sends its digest', async () => {
  const user = show()
  await user.type(screen.getByLabelText('Host'), '192.168.1.10')
  expect(await screen.findByText(CMD)).toBeInTheDocument()
  expect(screen.getByText(CPU)).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Start' }))
  const start = posts.find(([p]) => p === '/api/routers/ap1/tools/throughput/start')
  expect(start?.[1]).toEqual({
    mode: 'client',
    host: '192.168.1.10',
    port: 5201,
    protocol: 'tcp',
    reverse: false,
    duration_s: 10,
    udp_mbps: 10,
    digest: 'd1',
  })
})

test('a refused host shows the rule', async () => {
  const user = show()
  await user.type(screen.getByLabelText('Host'), 'x; reboot')
  expect(await screen.findByRole('alert')).toHaveTextContent(HOST_TEXT)
})

test('a run during a harness run shows why it was refused', async () => {
  startError = new ApiError(423, 'dima_night.py started 21:04 (PID 18244)', {})
  const user = show()
  await user.type(screen.getByLabelText('Host'), '192.168.1.10')
  await screen.findByText(CMD)
  await user.click(screen.getByRole('button', { name: 'Start' }))
  expect(await screen.findByText('dima_night.py started 21:04 (PID 18244)')).toHaveAttribute('role', 'alert')
})

test('a finished TCP run: the seconds and the totals', async () => {
  sessions = [session()]
  show()
  const table = await screen.findByRole('table', { name: 'Throughput' })
  expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Time', 'Mb/s', 'Retransmits'])
  expect(within(table).getAllByRole('cell').map((c) => c.textContent)).toEqual(['0–1 s', '94.2', '0'])
  expect(screen.getByText('Sent 95.0 Mb/s · received 94.0 Mb/s · router CPU 42 %')).toBeInTheDocument()
})

test('a UDP run shows jitter and loss', async () => {
  sessions = [
    session({
      intervals: [{ start_s: 0, end_s: 1, mbps: 20.0, retransmits: null, jitter_ms: 0.05, lost_pct: 0.5 }],
    }),
  ]
  show()
  const table = await screen.findByRole('table', { name: 'Throughput' })
  expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
    'Time',
    'Mb/s',
    'Jitter (ms)',
    'Lost (%)',
  ])
})

test('Stop asks the router to end the running one', async () => {
  sessions = [session({ running: true, summary: null })]
  const user = show()
  await user.click(await screen.findByRole('button', { name: 'Stop' }))
  expect(posts).toContainEqual(['/api/routers/ap1/tools/sessions/s1/stop', undefined])
})

test('a session that ended badly says why', async () => {
  sessions = [session({ error: 'Stopped by Bench Guard: dima_night.py started 21:04 (PID 18244)', summary: null })]
  show()
  expect(await screen.findByText('Stopped by Bench Guard: dima_night.py started 21:04 (PID 18244)')).toHaveAttribute(
    'role',
    'alert',
  )
})

test('server mode shows how to run iperf3 on the PC', async () => {
  const user = show()
  await user.selectOptions(screen.getByLabelText('The router'), 'server')
  expect(screen.queryByLabelText('Host')).toBeNull()
  expect(await screen.findByText(HINT)).toBeInTheDocument()
})
