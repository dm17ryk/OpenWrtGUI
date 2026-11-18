import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import type { LteRecoverJob } from '../../api/types'
import { RecoverPanel } from './RecoverPanel'

const posts: string[] = []

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    postJson: vi.fn(async (path: string) => {
      posts.push(path)
      return null
    }),
  }
})

beforeEach(() => {
  posts.length = 0
})

const NAMES = ['Put back the saved setup', 'Reconnect', 'Clear QMI state', "Turn off the modem's autoconnect", 'Restart the modem']

function job(over: Partial<LteRecoverJob>): LteRecoverJob {
  return {
    router_id: 'ap2',
    phase: 'running',
    diagnosis: ['session up but no packet-data handle'],
    rungs: NAMES.map((name) => ({ name, outcome: null, detail: null })),
    current: null,
    started_at: '2026-11-17T12:00:00',
    ended_at: null,
    detail: null,
    error: null,
    ...over,
  }
}

function show(j: LteRecoverJob) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RecoverPanel routerId="ap2" job={j} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return screen.getByRole('region', { name: 'Recover' })
}

test('it lists the diagnosis and the five rungs with their outcomes', () => {
  const rungs = NAMES.map((name, i) => ({ name, outcome: i === 0 ? 'skipped' : i === 1 ? 'not yet' : null, detail: null })) as LteRecoverJob['rungs']
  const panel = show(job({ rungs, current: 2 }))
  expect(panel).toHaveTextContent('session up but no packet-data handle')
  const list = within(panel).getByRole('list', { name: 'Steps' })
  expect(within(list).getAllByRole('listitem')).toHaveLength(5)
  expect(list).toHaveTextContent('Put back the saved setup: skipped')
  expect(list).toHaveTextContent('Reconnect: not yet')
  expect(list).toHaveTextContent('Clear QMI state: running')
})

test('Stop shows while it runs and posts the stop', async () => {
  const user = userEvent.setup()
  const panel = show(job({ current: 1 }))
  await user.click(within(panel).getByRole('button', { name: 'Stop' }))
  expect(posts).toEqual(['/api/routers/ap2/lte/recover/stop'])
})

test('a "not recovered" end offers Reboot router and says to power-cycle', () => {
  const detail = 'LTE did not come back. Reboot the router (System › Reboot), then power-cycle it if that does not help.'
  const panel = show(job({ phase: 'not recovered', detail, ended_at: '2026-11-17T12:04:00' }))
  expect(within(panel).getByRole('link', { name: 'Reboot router' })).toHaveAttribute('href', '/routers/ap2/system')
  expect(panel).toHaveTextContent('power-cycle it if that does not help')
  expect(within(panel).queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
})

test('a "works" end says there is nothing to do', () => {
  const panel = show(job({ phase: 'works', detail: 'LTE works; nothing to do.', ended_at: '2026-11-17T12:00:01' }))
  expect(panel).toHaveTextContent('LTE works; nothing to do.')
})

test('a failed end shows its error as an alert', () => {
  const error = 'ifdown lte: AP2 · office did not answer.'
  const panel = show(job({ phase: 'failed', error, ended_at: '2026-11-17T12:00:01' }))
  expect(within(panel).getByRole('alert')).toHaveTextContent(error)
})
