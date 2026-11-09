import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import type { CronState } from '../../api/types'
import { AP2_CRON_PLAN, AP2_CRON_RESULT, AP2_CRONTAB } from '../../testing/system'
import { CronTab } from './CronTab'

const calls: Array<{ path: string; body: unknown }> = []
let state: CronState = AP2_CRONTAB

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path === '/api/routers/ap2/system/crontab') return state
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body?: unknown) => {
      calls.push({ path, body })
      const text = (body as { text: string }).text
      if (path === '/api/routers/ap2/system/crontab/preview') {
        if (text.startsWith('61 ')) throw new actual.ApiError(422, 'line 1: minute is 0-59', null)
        return AP2_CRON_PLAN
      }
      if (path === '/api/routers/ap2/system/crontab/apply') return AP2_CRON_RESULT
      throw new Error(`unexpected ${path}`)
    }),
  }
})

beforeEach(() => {
  calls.length = 0
  state = AP2_CRONTAB
})

function renderTab() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CronTab routerId="ap2" routerName="AP2 · office" />
    </QueryClientProvider>,
  )
}

test('no crontab is no tasks, with cron idle', async () => {
  renderTab()
  expect(await screen.findByText('No scheduled tasks.')).toBeInTheDocument()
  expect(screen.getByText('cron is enabled and idle: it starts once there is a task')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Help: Scheduled tasks' })).toBeInTheDocument()
})

test('an added task previews the whole file and applies', async () => {
  const user = userEvent.setup()
  renderTab()
  await user.click(await screen.findByRole('button', { name: 'Add task' }))
  const task = screen.getByRole('group', { name: 'Task 1' })
  await user.clear(within(task).getByRole('textbox', { name: 'Minute' }))
  await user.type(within(task).getByRole('textbox', { name: 'Minute' }), '*/5')
  await user.type(within(task).getByRole('textbox', { name: 'Command' }), 'logger owg-test')
  const preview = await screen.findByRole('region', { name: 'Command preview' })
  expect(preview).toHaveTextContent('/etc/init.d/cron restart')
  expect(calls.at(-1)).toEqual({ path: '/api/routers/ap2/system/crontab/preview', body: { text: '*/5 * * * * logger owg-test\n' } })
  await user.click(screen.getByRole('button', { name: 'Apply' }))
  expect(calls.at(-1)?.path).toBe('/api/routers/ap2/system/crontab/apply')
  expect(await screen.findByRole('status', { name: 'Apply result' })).toHaveTextContent('Applied and checked')
})

test('a field cron cannot read shows the refusal with its line number', async () => {
  const user = userEvent.setup()
  renderTab()
  await user.click(await screen.findByRole('button', { name: 'Add task' }))
  const task = screen.getByRole('group', { name: 'Task 1' })
  await user.clear(within(task).getByRole('textbox', { name: 'Minute' }))
  await user.type(within(task).getByRole('textbox', { name: 'Minute' }), '61')
  await user.type(within(task).getByRole('textbox', { name: 'Command' }), 'logger x')
  expect(await screen.findByText('line 1: minute is 0-59')).toBeInTheDocument()
})

test('the text view edits the same file', async () => {
  const user = userEvent.setup()
  state = { ...AP2_CRONTAB, text: '# nightly\n0 3 * * * logger owg\n', tasks: [{ minute: '0', hour: '3', day: '*', month: '*', weekday: '*', command: 'logger owg' }] }
  renderTab()
  expect(await screen.findByRole('group', { name: 'Task 1' })).toBeInTheDocument()
  expect(screen.getByText('# nightly')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Edit as text' }))
  expect(screen.getByRole('textbox', { name: 'Crontab' })).toHaveValue('# nightly\n0 3 * * * logger owg\n')
})
