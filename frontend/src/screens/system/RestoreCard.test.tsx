import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { RebootJob, RestoreCheck } from '../../api/types'
import { AP2_BACKUP, AP2_RESTORE_CHECK, AP2_RESTORE_PLAN } from '../../testing/system'
import { RestoreCard } from './RestoreCard'

const base = '/api/routers/ap2/system'
const JOB = { kind: 'restore' as const, router_id: 'ap2', started_at: '2026-11-10T12:00:00', uptime_s: null, detail: null, error: null }
const REFUSAL = 'after the restore the app could not log in to AP2 · office'
let check: RestoreCheck = AP2_RESTORE_CHECK
let jobs: Array<RebootJob | null> = [null]
const calls: Array<{ path: string; body: unknown }> = []

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path === `${base}/backups`) return [AP2_BACKUP]
      if (path === `${base}/reboot`) return jobs.length > 1 ? jobs.shift() : jobs[0]
      if (path === `${base}`) return {}
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body?: unknown) => {
      calls.push({ path, body })
      if (path === `${base}/restore/check`) return check
      if (path === `${base}/restore/preview`) return AP2_RESTORE_PLAN
      if (path === `${base}/restore/start`) {
        jobs = [
          { ...JOB, phase: 'waiting' },
          { ...JOB, phase: 'back', uptime_s: 38, detail: 'AP2 · office is back after 61 s (uptime 38 s); every restored file matches the backup' },
        ]
        return { ...JOB, phase: 'armed' }
      }
      throw new Error(`unexpected ${path}`)
    }),
  }
})

beforeEach(() => {
  check = AP2_RESTORE_CHECK
  jobs = [null]
  calls.length = 0
})
afterEach(() => vi.useRealTimers())

function renderCard() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RestoreCard routerId="ap2" short="AP2" />
    </QueryClientProvider>,
  )
}

test('a refused restore names the reason and offers no preview', async () => {
  check = { ...AP2_RESTORE_CHECK, refusals: [REFUSAL] }
  const user = userEvent.setup()
  renderCard()
  expect(await screen.findByRole('combobox', { name: 'Backup to restore' })).toHaveValue(AP2_BACKUP.name)
  await user.click(screen.getByRole('button', { name: 'Check' }))
  const refused = await screen.findByRole('alert')
  expect(refused).toHaveTextContent('Not restored')
  expect(refused).toHaveTextContent(REFUSAL)
  expect(screen.queryByRole('region', { name: 'Command preview' })).not.toBeInTheDocument()
  expect(calls.map((c) => c.path)).toEqual([`${base}/restore/check`])
})

test('a checked backup lists its files, previews, asks once more, then follows the restore to back', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  renderCard()
  await user.click(await screen.findByRole('button', { name: 'Check' }))
  const files = await screen.findByRole('list', { name: 'Files in the backup' })
  expect(within(files).getAllByRole('listitem').map((li) => li.textContent)).toEqual(AP2_RESTORE_CHECK.files)
  const preview = await screen.findByRole('region', { name: 'Command preview' })
  expect(preview).toHaveTextContent('sysupgrade --restore-backup /tmp/owg/restore.tar.gz')
  await user.click(screen.getByRole('button', { name: 'Restore and reboot' }))
  await user.click(within(screen.getByRole('group', { name: 'Confirm restore' })).getByRole('button', { name: 'Restore now' }))
  expect(calls.at(-1)).toEqual({ path: `${base}/restore/start`, body: { name: AP2_BACKUP.name, digest: AP2_RESTORE_PLAN.digest } })
  expect(await screen.findByRole('status', { name: 'Restore' })).toHaveTextContent('Restored: AP2 reboots in 2 s')
  await vi.advanceTimersByTimeAsync(2100)
  expect(await screen.findByText(/Waiting for AP2 to answer/)).toBeInTheDocument()
  await vi.advanceTimersByTimeAsync(2100)
  expect(await screen.findByText(/every restored file matches the backup/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Check' })).toBeEnabled() // the job is over
})
