import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import type { GuardOut, PendingRestore, StepJob, StepPlanOut } from '../../api/types'
import { AP2_RADIO, PROVEN } from '../../testing/wifi'
import { StepThroughCard } from './StepThroughCard'

const calls: Array<{ path: string; body: unknown }> = []
const STEP_LINES = ["uci set wireless.radio0.htmode='NOHT'", "uci set wireless.radio0.channel='1'"]
const PLAN: StepPlanOut = {
  steps: [
    { index: 1, mode: 'g', channel: 1, txpower_dbm: null },
    { index: 2, mode: 'g', channel: 6, txpower_dbm: null },
  ],
  step_lines: [STEP_LINES, ["uci set wireless.radio0.channel='6'"]],
  restore_lines: ["uci set wireless.radio0.disabled='1'"],
  warnings: [],
  estimate_s: 60,
  digest: 'feedfacecafe0001',
}
const BASE: StepJob = {
  router_id: 'ap2',
  radio: 'radio0',
  phase: 'waiting for Next',
  index: 1,
  total: 2,
  current: { index: 1, mode: 'g', channel: 1, txpower_dbm: null },
  advance: 'manual',
  dwell_s: 60,
  station: null,
  phase_ends_at: null,
  results: [],
  restore_pending: false,
  csv_path: null,
  started_at: '2026-11-12T10:00:00',
  ended_at: null,
  detail: null,
  error: null,
}
const RESULT = {
  index: 1,
  mode: 'g' as const,
  channel: 1,
  txpower_dbm: null,
  proven: true,
  checks: PROVEN.checks,
  beacon: '6.0 Mb/s ×5',
  rejoin_s: null,
  rejoined: null,
  started_at: '2026-11-12T10:00:00',
  ended_at: '2026-11-12T10:01:00',
}
const CLEAR: GuardOut = { checked_at: '2026-11-12T10:00:00', live: false, reasons: [] }
let job: StepJob | null = null
let pending: PendingRestore[] = []
let guard: GuardOut = CLEAR
let previewError: string | null = null

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  const respond = async (path: string, body?: unknown): Promise<unknown> => {
    calls.push({ path, body })
    if (path === '/api/guard') return guard
    if (path === '/api/routers/ap2/wifi/stations') return []
    if (path === '/api/routers/ap2/wifi/step-through') return job
    if (path === '/api/step-through/pending') return pending
    if (path === '/api/routers/ap2/wifi/step-through/preview') {
      if (previewError) throw new actual.ApiError(422, previewError, {})
      return PLAN
    }
    if (path === '/api/routers/ap2/wifi/step-through/start') {
      job = BASE
      return job
    }
    if (path.endsWith('/step-through/next') || path.endsWith('/step-through/stop')) return job
    if (path === '/api/routers/ap2/wifi/step-through/restore') {
      pending = []
      return PROVEN
    }
    throw new Error(`unexpected ${path}`)
  }
  return {
    ...actual,
    apiFetch: vi.fn((path: string) => respond(path)),
    postJson: vi.fn((path: string, body?: unknown) => respond(path, body)),
  }
})

beforeEach(() => {
  calls.length = 0
  job = null
  pending = []
  guard = CLEAR
  previewError = null
})

function renderCard(onEnded: () => void = () => undefined) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <StepThroughCard routerId="ap2" short="AP2" radio={AP2_RADIO} onEnded={onEnded} />
    </QueryClientProvider>,
  )
}

async function tickG16() {
  const user = userEvent.setup()
  renderCard()
  const card = await screen.findByRole('region', { name: 'Step-through' })
  await user.click(within(card).getByRole('button', { name: 'Step mode g' }))
  await user.click(within(card).getByRole('button', { name: 'Step channel 1' }))
  await user.click(within(card).getByRole('button', { name: 'Step channel 6' }))
  return { user, card }
}

test('previews numbered steps and the restore', async () => {
  const { card } = await tickG16()
  const code = await within(card).findByRole('region', { name: 'Command preview' })
  expect(code.textContent).toContain('# Step 1 · 802.11g · channel 1')
  expect(code.textContent).toContain('# Step 2 · 802.11g · channel 6')
  expect(code.textContent).toContain('# Restore at the end')
  expect(within(card).getByText('Step-through preview: 2 steps, about 1 min')).toBeInTheDocument()
  const asked = calls.find((c) => c.path.endsWith('/step-through/preview'))
  expect(asked?.body).toMatchObject({ radio: 'radio0', modes: ['g'], channels: [1, 6], advance: 'timer' })
})

test('start sends the preview digest', async () => {
  const { user, card } = await tickG16()
  await within(card).findByRole('region', { name: 'Command preview' })
  await user.click(within(card).getByRole('button', { name: 'Start step-through' }))
  await waitFor(() => expect(calls.some((c) => c.path.endsWith('/step-through/start'))).toBe(true))
  const start = calls.find((c) => c.path.endsWith('/step-through/start'))
  expect(start?.body).toMatchObject({ digest: PLAN.digest, modes: ['g'], channels: [1, 6] })
})

test('running shows the step, Next and Stop', async () => {
  job = BASE
  const user = userEvent.setup()
  renderCard()
  const status = await screen.findByRole('status')
  expect(status).toHaveTextContent('Step 1 of 2 · 802.11g · channel 1 · waiting for Next')
  await user.click(screen.getByRole('button', { name: 'Next step' }))
  await user.click(screen.getByRole('button', { name: 'Stop and restore' }))
  expect(calls.map((c) => c.path)).toEqual(
    expect.arrayContaining(['/api/routers/ap2/wifi/step-through/next', '/api/routers/ap2/wifi/step-through/stop']),
  )
})

test('shows results and the CSV path', async () => {
  job = {
    ...BASE,
    phase: 'done',
    index: 2,
    current: null,
    results: [RESULT, { ...RESULT, index: 2, channel: 6, proven: false, checks: [{ name: 'beacon rate', ok: false, detail: 'no beacon seen in 5 s' }] }],
    csv_path: 'C:\\Users\\me\\Documents\\OpenWrtGUI\\steps-ap2-radio0-20261112-100000.csv',
    ended_at: '2026-11-12T10:03:00',
  }
  renderCard()
  const table = await screen.findByRole('table', { name: 'Step-through results' })
  const rows = within(table).getAllByRole('row')
  expect(rows).toHaveLength(3)
  expect(rows[1]).toHaveTextContent('proven')
  expect(rows[2]).toHaveTextContent('beacon rate: no beacon seen in 5 s')
  expect(screen.getByText(/steps-ap2-radio0-20261112-100000\.csv/)).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('Done: 2 steps, radio0 restored')
})

test('pending restore banner restores', async () => {
  pending = [{ router_id: 'ap2', radio: 'radio0', saved_at: '2026-11-12T09:00:00', options: {} }]
  const user = userEvent.setup()
  renderCard()
  expect(await screen.findByText(/radio0 was left at a step by a step-through that did not restore it/)).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Restore radio0' }))
  await waitFor(() => expect(calls.some((c) => c.path.endsWith('/step-through/restore'))).toBe(true))
  expect(calls.find((c) => c.path.endsWith('/step-through/restore'))?.body).toEqual({ radio: 'radio0' })
})

test('422 reason shown', async () => {
  previewError = 'Channel 14 is not allowed in country IL'
  const { card } = await tickG16()
  expect(await within(card).findByRole('alert')).toHaveTextContent('Channel 14 is not allowed in country IL')
})

test('start disabled while the guard is live', async () => {
  guard = { ...CLEAR, live: true, reasons: [{ kind: 'process', text: 'dima_night.py started 21:04 (PID 18244)' }] as GuardOut['reasons'] }
  const { card } = await tickG16()
  await within(card).findByRole('region', { name: 'Command preview' })
  expect(within(card).getByRole('button', { name: 'Start step-through' })).toBeDisabled()
  expect(within(card).getByText(/dima_night\.py started 21:04/)).toBeInTheDocument()
})

test('an ended run has the Wi-Fi screen read the radio again', async () => {
  job = { ...BASE, phase: 'done', current: null }
  const ended = vi.fn()
  renderCard(ended)
  await screen.findByRole('status')
  await waitFor(() => expect(ended).toHaveBeenCalled())
})
