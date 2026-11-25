import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import type { GuardOut, PinResult, SimState } from '../../api/types'
import { SimCard } from './SimCard'

const NEEDED: SimState = { pin: 'needed', tries_left: 3, puk_tries_left: 10, card: 'ready', can_enter_pin: true, note: null }
const BLOCKED_NOTE = 'The SIM is blocked: it needs its PUK, which the app does not offer'
const LAST_TRY_NOTE = 'One try left: enter the PIN in a phone or the D-Link UI, so a wrong PIN does not block the SIM'

let sim: SimState = NEEDED
let answer: PinResult | Error | 'pending' | null = null
let release: (() => void) | null = null
const posts: Array<{ path: string; body: unknown }> = []

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path === '/api/routers/ap2/lte/sim') return sim
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body?: unknown) => {
      posts.push({ path, body })
      if (path !== '/api/routers/ap2/lte/sim/pin') throw new Error(`unexpected ${path}`)
      if (answer === 'pending') {
        await new Promise<void>((resolve) => (release = resolve))
        return { accepted: true, sim: { ...NEEDED, pin: 'entered', can_enter_pin: false }, message: 'PIN accepted' }
      }
      if (answer instanceof Error) throw answer
      return answer
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
  sim = NEEDED
  answer = null
  release = null
  posts.length = 0
})

function renderSim(guard: GuardOut = CLEAR) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['guard'], guard)
  render(
    <QueryClientProvider client={client}>
      <SimCard routerId="ap2" />
    </QueryClientProvider>,
  )
  return client
}

test.each([
  [{ ...NEEDED, pin: 'off', tries_left: null, can_enter_pin: false }, 'PIN off'],
  [NEEDED, 'PIN needed: 3 tries left'],
  [{ ...NEEDED, pin: 'entered', can_enter_pin: false }, 'PIN entered'],
  [{ ...NEEDED, pin: 'blocked', tries_left: 0, can_enter_pin: false, note: BLOCKED_NOTE }, BLOCKED_NOTE],
] as Array<[SimState, string]>)('shows the status line for %#', async (state, line) => {
  sim = state
  renderSim()
  const card = await screen.findByRole('region', { name: 'SIM' })
  expect(await screen.findByText(line)).toBeInTheDocument()
  expect(card).toHaveTextContent('SIM')
  expect(screen.getByRole('button', { name: 'Help: SIM PIN' })).toBeInTheDocument()
})

test('the Enter PIN form shows only when the SIM can take a PIN', async () => {
  sim = { ...NEEDED, pin: 'off', can_enter_pin: false }
  renderSim()
  await screen.findByText('PIN off')
  expect(screen.queryByRole('button', { name: 'Enter PIN' })).not.toBeInTheDocument()
  expect(screen.queryByLabelText('SIM PIN')).not.toBeInTheDocument()
})

test('the PIN field is a password field for digits and is not remembered by the browser', async () => {
  renderSim()
  const field = await screen.findByLabelText('SIM PIN')
  expect(field).toHaveAttribute('type', 'password')
  expect(field).toHaveAttribute('inputmode', 'numeric')
  expect(field).toHaveAttribute('autocomplete', 'off')
})

test('a refused PIN empties the field, shows the answer and reads the SIM again', async () => {
  const user = userEvent.setup()
  answer = { accepted: false, sim: { ...NEEDED, tries_left: 2 }, message: 'The SIM did not take the PIN: 2 tries left' }
  const client = renderSim()
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  const field = await screen.findByLabelText('SIM PIN')
  await user.type(field, '1234')
  await user.click(screen.getByRole('button', { name: 'Enter PIN' }))
  expect(await screen.findByText('The SIM did not take the PIN: 2 tries left')).toBeInTheDocument()
  expect(posts).toEqual([{ path: '/api/routers/ap2/lte/sim/pin', body: { pin: '1234' } }])
  expect(screen.getByLabelText('SIM PIN')).toHaveValue('')
  expect(document.body).not.toHaveTextContent('1234')
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['lte-sim', 'ap2'] })
  // the PIN is never put into react-query's cache
  expect(JSON.stringify(client.getQueryCache().getAll().map((q) => q.state.data))).not.toContain('1234')
})

test('an accepted PIN says so and the field is empty', async () => {
  const user = userEvent.setup()
  answer = { accepted: true, sim: { ...NEEDED, pin: 'entered', can_enter_pin: false }, message: 'PIN accepted' }
  renderSim()
  await user.type(await screen.findByLabelText('SIM PIN'), '4321')
  await user.click(screen.getByRole('button', { name: 'Enter PIN' }))
  expect(await screen.findByText('PIN accepted')).toBeInTheDocument()
  expect(document.body).not.toHaveTextContent('4321')
})

test('the PIN field is locked while the verify is pending, and empty after it settles', async () => {
  const user = userEvent.setup()
  answer = 'pending'
  renderSim()
  const field = await screen.findByLabelText('SIM PIN')
  await user.type(field, '1234')
  await user.click(screen.getByRole('button', { name: 'Enter PIN' }))
  await waitFor(() => expect(field).toBeDisabled())
  expect(field).toHaveValue('')
  release?.()
  expect(await screen.findByText('PIN accepted')).toBeInTheDocument()
  expect(field).toHaveValue('')
  expect(document.body).not.toHaveTextContent('1234')
})

test('a refusal from the server shows its text and still empties the field', async () => {
  const user = userEvent.setup()
  const { ApiError } = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  answer = new ApiError(409, 'One try left: enter the PIN elsewhere', {})
  renderSim()
  await user.type(await screen.findByLabelText('SIM PIN'), '5555')
  await user.click(screen.getByRole('button', { name: 'Enter PIN' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('One try left: enter the PIN elsewhere')
  expect(screen.getByLabelText('SIM PIN')).toHaveValue('')
  expect(document.body).not.toHaveTextContent('5555')
})

test('with one try left the card shows the note and no form', async () => {
  sim = { ...NEEDED, tries_left: 1, can_enter_pin: false, note: LAST_TRY_NOTE }
  renderSim()
  expect(await screen.findByText('PIN needed: 1 try left')).toBeInTheDocument()
  expect(screen.getByText(LAST_TRY_NOTE)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Enter PIN' })).not.toBeInTheDocument()
})

test('a live harness run disables Enter PIN and says why', async () => {
  const user = userEvent.setup()
  renderSim(LIVE)
  await user.type(await screen.findByLabelText('SIM PIN'), '1234')
  const button = screen.getByRole('button', { name: 'Enter PIN' })
  expect(button).toBeDisabled()
  expect(button).toHaveAttribute('title', expect.stringContaining('Waits for the run: '))
  await waitFor(() => expect(posts).toHaveLength(0))
})
