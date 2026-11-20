import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { SendResult, ToolSessionView } from '../../api/types'
import { TrafficTab } from './TrafficTab'

const LISTEN = 'echo "OWG-PID $$"; exec timeout -s KILL 60 socat TCP-LISTEN:9100,reuseaddr,fork SYSTEM:...'
const SEND = 'head -c 1000 /dev/zero | timeout -s KILL 30 socat -u - TCP:192.168.1.10:9101,connect-timeout=5 2>&1'

const posts: Array<[string, unknown]> = []
let sessions: ToolSessionView[] = []
let sendResult: SendResult = { ok: true, detail: 'Sent 1000 bytes to 192.168.1.10 port 9101 over TCP.' }

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
      if (path.endsWith('/traffic/listen/preview')) return { lines: [LISTEN], warnings: [], digest: 'l1' }
      if (path.endsWith('/traffic/listen/start')) return listening({ running: true })
      if (path.endsWith('/traffic/send/preview')) return { lines: [SEND], warnings: [], digest: 'x1' }
      if (path.endsWith('/traffic/send/apply')) return sendResult
      if (path.endsWith('/stop')) return listening({ running: false })
      throw new Error(`unexpected ${path}`)
    }),
  }
})

function listening(over: Partial<ToolSessionView> = {}): ToolSessionView {
  return {
    id: 'l1',
    router_id: 'ap1',
    kind: 'listen',
    title: 'Traffic listen',
    command: LISTEN,
    started_at: 1000,
    ends_at: 1060,
    running: false,
    intervals: [],
    summary: null,
    peers: [{ address: '192.168.1.10', port: 51515, bytes: 6, first_hex: '68656c6c6f0a' }],
    notes: [],
    error: null,
    ...over,
  }
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  posts.length = 0
  sessions = []
  sendResult = { ok: true, detail: 'Sent 1000 bytes to 192.168.1.10 port 9101 over TCP.' }
})

afterEach(() => {
  vi.useRealTimers()
})

function show() {
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TrafficTab routerId="ap1" />
    </QueryClientProvider>,
  )
  return user
}

test('Listen: its fields, the preview and Start with the digest', async () => {
  const user = show()
  const listen = screen.getByRole('region', { name: 'Listen' })
  for (const label of ['Protocol', 'Port', 'Duration (s)']) {
    expect(within(listen).getByLabelText(label)).toBeInTheDocument()
  }
  expect(await within(listen).findByText(LISTEN)).toBeInTheDocument()
  await user.click(within(listen).getByRole('button', { name: 'Start' }))
  expect(posts).toContainEqual([
    '/api/routers/ap1/tools/traffic/listen/start',
    { protocol: 'tcp', port: 9100, duration_s: 60, digest: 'l1' },
  ])
})

test('Listen: the peers and their first bytes', async () => {
  sessions = [listening()]
  show()
  const table = await screen.findByRole('table', { name: 'Peers' })
  expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
    'Peer',
    'Bytes',
    'First bytes (hex)',
  ])
  expect(within(table).getAllByRole('cell').map((c) => c.textContent)).toEqual([
    '192.168.1.10:51515',
    '6',
    '68656c6c6f0a',
  ])
})

test('Listen: Stop ends a running listen', async () => {
  sessions = [listening({ running: true })]
  const user = show()
  const listen = screen.getByRole('region', { name: 'Listen' })
  await user.click(await within(listen).findByRole('button', { name: 'Stop' }))
  expect(posts).toContainEqual(['/api/routers/ap1/tools/sessions/l1/stop', undefined])
})

test('Send: its fields switch between a count and a line of text', async () => {
  const user = show()
  const send = screen.getByRole('region', { name: 'Send' })
  for (const label of ['Protocol', 'Host', 'Port', 'What', 'Count']) {
    expect(within(send).getByLabelText(label)).toBeInTheDocument()
  }
  const what = within(send).getByLabelText('What')
  expect(within(what).getAllByRole('option').map((o) => o.textContent)).toEqual(['Bytes (zeros)', 'A line of text'])
  await user.selectOptions(what, 'text')
  expect(within(send).getByLabelText('Text')).toBeInTheDocument()
  expect(within(send).queryByLabelText('Count')).toBeNull()
})

test('Send: the result says what was sent', async () => {
  const user = show()
  const send = screen.getByRole('region', { name: 'Send' })
  await user.type(within(send).getByLabelText('Host'), '192.168.1.10')
  expect(await within(send).findByText(SEND)).toBeInTheDocument()
  await user.click(within(send).getByRole('button', { name: 'Send' }))
  expect(await within(send).findByText('Sent 1000 bytes to 192.168.1.10 port 9101 over TCP.')).toBeInTheDocument()
  const apply = posts.find(([p]) => p === '/api/routers/ap1/tools/traffic/send/apply')
  expect(apply?.[1]).toEqual({
    protocol: 'tcp',
    host: '192.168.1.10',
    port: 9101,
    what: 'bytes',
    count: 1000,
    text: '',
    digest: 'x1',
  })
})

test('Send: a refusal is an alert', async () => {
  sendResult = { ok: false, detail: 'connect(5, AF=2 192.168.1.10:1, 16): Connection refused' }
  const user = show()
  const send = screen.getByRole('region', { name: 'Send' })
  await user.type(within(send).getByLabelText('Host'), '192.168.1.10')
  await within(send).findByText(SEND)
  await user.click(within(send).getByRole('button', { name: 'Send' }))
  expect(await within(send).findByText('connect(5, AF=2 192.168.1.10:1, 16): Connection refused')).toHaveAttribute(
    'role',
    'alert',
  )
})
