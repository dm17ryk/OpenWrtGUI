import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import type { FramePlanOut, FrameState, FrameWindow } from '../../api/types'
import { FrameAnalysis } from './FrameAnalysis'

const calls: Array<{ path: string; body: unknown }> = []
const PLAN: FramePlanOut = {
  lines: [
    'iw dev owgmon0 del 2>/dev/null; iw phy phy0 interface add owgmon0 type monitor && ip link set owgmon0 up',
    'iw dev owgmon0 set monitor fcsfail control otherbss',
    'timeout 3 tcpdump -i owgmon0 -e -n -l -v -s 128 -c 2000  # every 5 s, for up to 30 minutes',
    'iw dev owgmon0 del',
  ],
  warnings: ['Costs router CPU: tcpdump runs 3 s of every 5 s for up to 30 minutes.'],
  digest: 'feedfacecafe0002',
}
const WINDOW: FrameWindow = {
  seconds: 3,
  frames: 102,
  bad_fcs: 2,
  rx: { frames: 40, retries: 4, rates: { '54.0': 40 }, signal_hist: { '-50': 30, '-55': 10 } },
  tx: { frames: 60, retries: 0, rates: { 'MCS 7': 60 }, signal_hist: {} },
  dropped: 0,
}
const OFF: FrameState = {
  running: false,
  started_at: null,
  ends_at: null,
  windows: 0,
  fcs_reported: true,
  last: null,
  totals: null,
  note: null,
  error: null,
}
const RUNNING: FrameState = {
  ...OFF,
  running: true,
  started_at: '2026-11-12T10:00:00',
  ends_at: '2099-11-12T10:30:00',
  windows: 12,
  last: WINDOW,
  totals: { ...WINDOW, frames: 1224, bad_fcs: 24 },
  note: 'monitor added again after a Wi-Fi reload',
}
let state: FrameState = OFF
let startError: string | null = null

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  const respond = async (path: string, body?: unknown): Promise<unknown> => {
    calls.push({ path, body })
    const base = '/api/routers/ap1/rf/radio0/frames'
    if (path === base) return state
    if (path === `${base}/preview`) return PLAN
    if (path === `${base}/start`) {
      if (startError) throw new actual.ApiError(422, startError, {})
      state = RUNNING
      return state
    }
    if (path === `${base}/stop`) {
      state = OFF
      return state
    }
    throw new Error(`unexpected ${path}`)
  }
  return { ...actual, apiFetch: vi.fn((p: string) => respond(p)), postJson: vi.fn((p: string, b?: unknown) => respond(p, b)) }
})

beforeEach(() => {
  calls.length = 0
  state = OFF
  startError = null
})

function renderFrames(live: FrameState | null = null) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <FrameAnalysis routerId="ap1" radio="radio0" live={live} retryPct={2.5} />
    </QueryClientProvider>,
  )
}

test('frames preview then start', async () => {
  const user = userEvent.setup()
  renderFrames()
  const card = await screen.findByRole('region', { name: 'Frame analysis' })
  await user.click(within(card).getByRole('button', { name: 'Frame analysis…' }))
  const code = await within(card).findByRole('region', { name: 'Command preview' })
  expect(code.textContent).toContain('iw dev owgmon0 set monitor fcsfail control otherbss')
  expect(within(card).getByText(/Costs router CPU/)).toBeInTheDocument()
  await user.click(within(card).getByRole('button', { name: 'Start frame analysis' }))
  await waitFor(() => expect(calls.some((c) => c.path.endsWith('/frames/start'))).toBe(true))
  expect(calls.find((c) => c.path.endsWith('/frames/start'))?.body).toEqual({ digest: PLAN.digest })
})

test('frames message updates bars and totals', async () => {
  renderFrames(RUNNING)
  const card = await screen.findByRole('region', { name: 'Frame analysis' })
  expect(within(card).getByText(/window 12 · 3 s of every 5 s/)).toBeInTheDocument()
  expect(within(card).getByRole('list', { name: 'Rate mix RX at AP, last window' })).toHaveTextContent('54.0 Mb/s')
  expect(within(card).getByRole('list', { name: 'Rate mix TX from AP, last window' })).toHaveTextContent('MCS 7')
  expect(within(card).getAllByText('Retry flag RX: 10.0 %').length).toBeGreaterThan(0)
  expect(within(card).getByText('Bad FCS: 2.0 % of 102 frames')).toBeInTheDocument()
  expect(within(card).getByText('monitor added again after a Wi-Fi reload')).toBeInTheDocument()
  expect(within(card).getByRole('button', { name: 'Stop frame analysis' })).toBeEnabled()
})

test('frames stopped shows why', async () => {
  renderFrames({ ...OFF, windows: 3, error: 'Bench Guard: dima_night.py started 21:04 (PID 18244)' })
  const card = await screen.findByRole('region', { name: 'Frame analysis' })
  expect(within(card).getByText(/Stopped: Bench Guard: dima_night\.py/)).toBeInTheDocument()
})

test('a refused start shows the reason', async () => {
  startError = 'radio0 is parked: nothing of its own to analyse'
  const user = userEvent.setup()
  renderFrames()
  const card = await screen.findByRole('region', { name: 'Frame analysis' })
  await user.click(within(card).getByRole('button', { name: 'Frame analysis…' }))
  await within(card).findByRole('region', { name: 'Command preview' })
  await user.click(within(card).getByRole('button', { name: 'Start frame analysis' }))
  expect(await within(card).findByRole('alert')).toHaveTextContent('radio0 is parked')
})
