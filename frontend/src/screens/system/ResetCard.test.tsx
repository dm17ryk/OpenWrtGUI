import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { RebootJob } from '../../api/types'
import { AP2_RESET_PLAN } from '../../testing/system'
import { ResetCard } from './ResetCard'

const base = '/api/routers/ap2/system'
const JOB = { kind: 'reset' as const, router_id: 'ap2', started_at: '2026-11-10T12:00:00', uptime_s: null, detail: null, error: null }
let jobs: Array<RebootJob | null> = [null]
const calls: Array<{ path: string; body: unknown }> = []

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path === `${base}/reboot`) return jobs.length > 1 ? jobs.shift() : jobs[0]
      if (path === '/api/routers' || path === '/api/routers/ap2') return []
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body?: unknown) => {
      calls.push({ path, body })
      if (path === `${base}/reset/preview`) return AP2_RESET_PLAN
      if (path === `${base}/reset/start`) {
        jobs = [
          { ...JOB, phase: 'waiting' },
          { ...JOB, phase: 'reset', detail: 'AP2 · office is resetting to defaults: it comes back as 192.168.1.1 with no password' },
        ]
        return { ...JOB, phase: 'armed' }
      }
      throw new Error(`unexpected ${path}`)
    }),
  }
})

beforeEach(() => {
  jobs = [null]
  calls.length = 0
})
afterEach(() => vi.useRealTimers())

function renderCard() {
  render(
    <MemoryRouter>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ResetCard routerId="ap2" routerName="AP2 · office" />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

test("Start needs the router's name typed and the alone tick, then the job ends with the add-again note", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  renderCard()
  await user.click(await screen.findByRole('button', { name: 'Preview reset' }))
  expect(await screen.findByRole('region', { name: 'Command preview' })).toHaveTextContent('firstboot -r -y')
  expect(screen.getByText(AP2_RESET_PLAN.warnings[0])).toBeInTheDocument()
  const start = screen.getByRole('button', { name: 'Start reset' })
  expect(start).toBeDisabled()
  const name = screen.getByRole('textbox', { name: 'Type AP2 · office to confirm' })
  await user.type(name, 'AP2')
  await user.click(screen.getByRole('checkbox', { name: "AP2 · office is alone on this PC's network" }))
  expect(start).toBeDisabled() // the name is not complete
  await user.clear(name)
  await user.type(name, 'AP2 · office')
  expect(start).toBeEnabled()
  await user.click(screen.getByRole('checkbox', { name: "AP2 · office is alone on this PC's network" }))
  expect(start).toBeDisabled() // the tick is off again
  await user.click(screen.getByRole('checkbox', { name: "AP2 · office is alone on this PC's network" }))
  await user.click(start)
  expect(calls.at(-1)).toEqual({ path: `${base}/reset/start`, body: { digest: AP2_RESET_PLAN.digest, confirm_name: 'AP2 · office', alone: true } })
  expect(await screen.findByRole('status', { name: 'Reset' })).toHaveTextContent('Armed: AP2 erases its settings in 2 s')
  await vi.advanceTimersByTimeAsync(2100)
  expect(await screen.findByText('Waiting for AP2 to stop answering…')).toBeInTheDocument()
  await vi.advanceTimersByTimeAsync(2100)
  expect(await screen.findByText(/comes back as 192.168.1.1 with no password/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Add again' })).toHaveAttribute('href', '/add?host=192.168.1.1')
})
