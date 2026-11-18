import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { RfMessage } from '../../api/types'
import { AP2 } from '../../testing/fixtures'
import { AP2_WIFI } from '../../testing/wifi'
import { RfLive } from './RfLive'
import { rfSample as sample } from '../../testing/rf'

vi.mock('uplot', () => ({
  default: class {
    setData(): void {}
    setSize(): void {}
    destroy(): void {}
  },
}))

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path === '/api/routers/ap1') return { ...AP2, record: { ...AP2.record, id: 'ap1', name: 'AP1 · bench' } }
      if (path === '/api/routers/ap1/wifi') return AP2_WIFI
      if (path === '/api/routers/ap1/luci/pages') return []
      throw new Error(`unexpected ${path}`)
    }),
  }
})

class FakeSocket {
  static last: FakeSocket | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  sent: unknown[] = []
  readonly url: string
  constructor(url: string) {
    this.url = url
    FakeSocket.last = this
  }
  send(data: string): void {
    this.sent.push(JSON.parse(data))
  }
  close(): void {}
  emit(msg: RfMessage): void {
    act(() => this.onmessage?.({ data: JSON.stringify(msg) }))
  }
}

beforeEach(() => vi.stubGlobal('WebSocket', FakeSocket))
afterEach(() => vi.unstubAllGlobals())

function renderRf(path = '/routers/ap1/rf') {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/routers/:id/rf" element={<RfLive />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('samples fill the tiles and the RX/TX columns', async () => {
  renderRf()
  expect(await screen.findByRole('heading', { name: 'RF live', level: 1 })).toBeInTheDocument()
  expect(FakeSocket.last?.url).toContain('/ws/rf/ap1')
  FakeSocket.last?.emit({ type: 'rf', sample: sample(0) })
  expect(screen.getByRole('region', { name: 'Channel' })).toHaveTextContent('1 · HT20')
  expect(screen.getByRole('region', { name: 'Noise floor' })).toHaveTextContent('not reported')
  expect(screen.getByRole('region', { name: 'Air busy' })).toHaveTextContent('23 %')
  expect(screen.getByRole('region', { name: 'RX at AP · station → AP' })).toHaveTextContent('−52 dBm')
  expect(screen.getByRole('region', { name: 'TX from AP · AP → station' })).toHaveTextContent('MCS 7 · HT20 · long GI')
  for (const name of ['RF live', 'Radio', 'RX at AP', 'TX from AP', 'Charts', 'Which rates reach the station', 'Record to CSV']) {
    expect(screen.getByRole('button', { name: `Help: ${name}` })).toBeInTheDocument()
  }
})

test('a station that left is marked', async () => {
  renderRf()
  await screen.findByRole('heading', { name: 'RF live', level: 1 })
  FakeSocket.last?.emit({ type: 'rf', sample: sample(0) })
  FakeSocket.last?.emit({ type: 'rf', sample: { ...sample(1, []), left: ['f4:12:fa:f3:57:68'] } })
  expect(screen.getByText('panel left')).toBeInTheDocument()
})

test('Record asks the app and shows where the file goes', async () => {
  const user = userEvent.setup()
  renderRf()
  await screen.findByRole('heading', { name: 'RF live', level: 1 })
  await user.click(screen.getByRole('button', { name: 'Record to CSV' }))
  expect(FakeSocket.last?.sent).toContainEqual({ type: 'record', on: true })
  FakeSocket.last?.emit({ type: 'recording', path: 'C:\\Users\\me\\Documents\\OpenWrtGUI\\rf-ap1-radio0-20261105-090000.csv' })
  expect(screen.getByText(/rf-ap1-radio0-20261105-090000\.csv/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Stop recording' })).toBeInTheDocument()
})

test('a lost connection says the recording stopped and greys Record until it is back', async () => {
  // the final review: the app stops a recording when its socket closes; the screen must not still claim one
  renderRf()
  await screen.findByRole('heading', { name: 'RF live', level: 1 })
  FakeSocket.last?.emit({ type: 'recording', path: 'C:\\Users\\me\\Documents\\OpenWrtGUI\\rf-ap1-radio0-20261105-090000.csv' })
  const lost = FakeSocket.last?.onclose as unknown as ((ev: { code: number; reason: string }) => void) | null
  act(() => lost?.({ code: 1006, reason: '' }))
  expect(screen.getByText('Recording stopped when the connection was lost: C:\\Users\\me\\Documents\\OpenWrtGUI\\rf-ap1-radio0-20261105-090000.csv')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Record to CSV' })).toBeDisabled()
})

test('an idle radio says why', async () => {
  renderRf()
  await screen.findByRole('heading', { name: 'RF live', level: 1 })
  FakeSocket.last?.emit({ type: 'rf-idle', reason: 'radio0 is parked' })
  expect(screen.getByRole('status')).toHaveTextContent('radio0 is parked')
})

const ratesAsked = (): number => FakeSocket.last?.sent.filter((m) => (m as { type?: string }).type === 'rates').length ?? 0

test('rates are not asked while the card is closed', async () => {
  renderRf('/routers/ap1/rf?station=f4:12:fa:f3:57:68')
  await screen.findByRole('heading', { name: 'RF live', level: 1 })
  FakeSocket.last?.emit({ type: 'rf', sample: sample(0) })
  expect(screen.getByRole('button', { name: 'Show rates' })).toHaveAttribute('aria-expanded', 'false')
  expect(ratesAsked()).toBe(0)
})

test('opening the card asks at once and every 5 s; closing stops it', async () => {
  renderRf('/routers/ap1/rf?station=f4:12:fa:f3:57:68')
  await screen.findByRole('heading', { name: 'RF live', level: 1 })
  vi.useFakeTimers()
  try {
    FakeSocket.last?.emit({ type: 'rf', sample: sample(0) })
    fireEvent.click(screen.getByRole('button', { name: 'Show rates' }))
    expect(ratesAsked()).toBe(1)
    act(() => vi.advanceTimersByTime(5000))
    expect(ratesAsked()).toBe(2)
    fireEvent.click(screen.getByRole('button', { name: 'Hide rates' }))
    act(() => vi.advanceTimersByTime(10000))
    expect(ratesAsked()).toBe(2)
  } finally {
    vi.useRealTimers()
  }
})

test('a rates error is shown', async () => {
  const user = userEvent.setup()
  renderRf('/routers/ap1/rf?station=f4:12:fa:f3:57:68')
  await screen.findByRole('heading', { name: 'RF live', level: 1 })
  FakeSocket.last?.emit({ type: 'rf', sample: sample(0) })
  await user.click(screen.getByRole('button', { name: 'Show rates' }))
  FakeSocket.last?.emit({ type: 'rates', mac: 'f4:12:fa:f3:57:68', error: 'No rate statistics from the router for this station' })
  expect(screen.getByText('No rate statistics from the router for this station')).toBeInTheDocument()
})
