import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { downloadFile } from '../../api/client'
import type { BackupFile, RebootJob } from '../../api/types'
import { AP2_REBOOT_PLAN } from '../../testing/system'
import { BackupTab } from './BackupTab'

const SAVED: BackupFile = { name: 'ap2-20261109-120000.tar.gz', size: 7424, created_at: '2026-11-09T12:00:00+02:00' }
const JOB = { router_id: 'ap2', started_at: '2026-11-09T12:00:00', uptime_s: null, detail: null, error: null }
let backups: BackupFile[] = []
let jobs: Array<RebootJob | null> = [null]
const calls: Array<{ path: string; body: unknown }> = []

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    downloadFile: vi.fn(async () => undefined),
    apiFetch: vi.fn(async (path: string) => {
      if (path === '/api/routers/ap2/system/backups') return backups
      if (path === '/api/routers/ap2/system/reboot') return jobs.length > 1 ? jobs.shift() : jobs[0]
      if (path === '/api/guard') return { live: false, reasons: [], checked_at: '2026-11-09T12:00:00' }
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body?: unknown) => {
      calls.push({ path, body })
      if (path === '/api/routers/ap2/system/backup') {
        backups = [SAVED]
        return SAVED
      }
      if (path === '/api/routers/ap2/system/reboot/preview') return AP2_REBOOT_PLAN
      if (path === '/api/routers/ap2/system/reboot/start') {
        jobs = [
          { ...JOB, phase: 'waiting' },
          { ...JOB, phase: 'back', uptime_s: 41, detail: 'AP2 · office is back after 63 s (uptime 41 s)' },
        ]
        return { ...JOB, phase: 'armed' }
      }
      throw new Error(`unexpected ${path}`)
    }),
  }
})

beforeEach(() => {
  backups = []
  jobs = [null]
  calls.length = 0
})
afterEach(() => vi.useRealTimers())

function renderTab() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <BackupTab routerId="ap2" routerName="AP2 · office" />
    </QueryClientProvider>,
  )
}

test('a backup is created, listed and downloaded', async () => {
  const user = userEvent.setup()
  renderTab()
  expect(await screen.findByText('No backups of AP2 saved yet.')).toBeInTheDocument()
  expect(screen.getByText(/password hash/)).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Create backup' }))
  const table = await screen.findByRole('table', { name: 'Backups' })
  expect(table).toHaveTextContent('ap2-20261109-120000.tar.gz')
  expect(table).toHaveTextContent('7.3 KiB')
  await user.click(within(table).getByRole('button', { name: 'Download' }))
  expect(downloadFile).toHaveBeenCalledWith('/api/routers/ap2/system/backups/ap2-20261109-120000.tar.gz', 'ap2-20261109-120000.tar.gz')
  expect(screen.getByRole('button', { name: 'Help: Backup' })).toBeInTheDocument()
})

test('a reboot is confirmed, then followed: armed, waiting, back with the new uptime', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  renderTab()
  await user.click(await screen.findByRole('button', { name: 'Preview reboot' }))
  const preview = await screen.findByRole('region', { name: 'Command preview' })
  expect(preview).toHaveTextContent('start-stop-daemon')
  expect(screen.getByText('AP2 · office is offline for about 60-90 s while it restarts')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Reboot AP2' }))
  const confirm = screen.getByRole('group', { name: 'Confirm reboot' })
  await user.click(within(confirm).getByRole('button', { name: 'Reboot now' }))
  expect(calls.at(-1)).toEqual({ path: '/api/routers/ap2/system/reboot/start', body: { digest: AP2_REBOOT_PLAN.digest } })
  const status = await screen.findByRole('status', { name: 'Reboot' })
  expect(status).toHaveTextContent('Armed')
  await vi.advanceTimersByTimeAsync(2100)
  expect(await screen.findByText(/Waiting for AP2 to answer/)).toBeInTheDocument()
  await vi.advanceTimersByTimeAsync(2100)
  expect(await screen.findByText('AP2 · office is back after 63 s (uptime 41 s)')).toBeInTheDocument()
})
