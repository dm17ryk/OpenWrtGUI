import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { ApiError, postJson } from '../api/client'
import type { RotationJob, RotationPreview } from '../api/types'
import { KeyRotation } from './KeyRotation'

vi.mock('../api/client', async (orig) => {
  const actual = await orig<typeof import('../api/client')>()
  return {
    ...actual,
    postJson: vi.fn(async () => ({})),
    apiFetch: vi.fn(async () => {
      throw new Error('should be cached')
    }),
  }
})

const PREVIEW: RotationPreview = {
  lines: [
    "Make a new app key, then for each router: add the new key, log in with it, remove the old key's line. Other lines in authorized_keys are not changed.",
    'AP2 · office (192.168.1.2): moves to the new key',
    'AP3 · QA stands: skipped, the app key is not installed on it',
  ],
  warnings: ['AP1 · bench does not answer now: it stays on the old key until you retry'],
  digest: 'd1g3st',
}

function job(phase: RotationJob['phase'], rows: RotationJob['routers'], detail: string | null = null): RotationJob {
  return {
    phase,
    old_fingerprint: 'SHA256:old',
    new_fingerprint: 'SHA256:new',
    routers: rows,
    started_at: '2026-11-18T18:00:00',
    ended_at: phase === 'running' ? null : '2026-11-18T18:00:05',
    detail,
  }
}

function renderRotation(current: RotationJob | null = null) {
  const client = new QueryClient()
  client.setQueryData(['app-key-rotation'], current)
  render(
    <QueryClientProvider client={client}>
      <KeyRotation />
    </QueryClientProvider>,
  )
  return client
}

beforeEach(() => vi.mocked(postJson).mockReset())

test('the preview lists its lines and Start posts its digest', async () => {
  const user = userEvent.setup()
  vi.mocked(postJson).mockResolvedValueOnce(PREVIEW).mockResolvedValueOnce(job('running', []))
  renderRotation()
  await user.click(screen.getByRole('button', { name: 'Rotate key…' }))
  const preview = screen.getByRole('region', { name: 'Rotation preview' })
  for (const line of PREVIEW.lines) expect(within(preview).getByText(line)).toBeInTheDocument()
  expect(within(preview).getByText(PREVIEW.warnings[0])).toBeInTheDocument()
  await user.click(within(preview).getByRole('button', { name: 'Start' }))
  expect(vi.mocked(postJson)).toHaveBeenLastCalledWith('/api/app-key/rotation', { digest: 'd1g3st' })
})

test('starting a rotation refreshes the key card so the new key shows', async () => {
  const user = userEvent.setup()
  vi.mocked(postJson).mockResolvedValueOnce(PREVIEW).mockResolvedValueOnce(job('running', []))
  const client = renderRotation()
  const spy = vi.spyOn(client, 'invalidateQueries')
  await user.click(screen.getByRole('button', { name: 'Rotate key…' }))
  await user.click(screen.getByRole('button', { name: 'Start' }))
  expect(spy).toHaveBeenCalledWith({ queryKey: ['app-key'] })
})

test('a running job counts the routers done and offers Stop', () => {
  renderRotation(
    job('running', [
      { router_id: 'ap1', name: 'AP1 · bench', state: 'moved', detail: null },
      { router_id: 'ap2', name: 'AP2 · office', state: 'proving', detail: null },
    ]),
  )
  expect(screen.getByText('Moving the app key: 1 of 2 routers done.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
})

test('a pending job says the old key stays and Retry posts the router', async () => {
  const user = userEvent.setup()
  vi.mocked(postJson).mockResolvedValueOnce(job('running', []))
  renderRotation(
    job('pending', [
      { router_id: 'ap2', name: 'AP2 · office', state: 'moved', detail: null },
      { router_id: 'ap3', name: 'AP3 · lab', state: 'failed', detail: 'AP3 · lab did not answer: it stays on the old key' },
    ]),
  )
  expect(
    screen.getByText('1 router(s) still on the old key. The old key stays on this PC until every router has the new one.'),
  ).toBeInTheDocument()
  const row = within(screen.getByRole('table', { name: 'Key rotation' })).getByRole('row', { name: /AP3 · lab/ })
  expect(row).toHaveTextContent('did not answer')
  await user.click(within(row).getByRole('button', { name: 'Retry' }))
  expect(vi.mocked(postJson)).toHaveBeenLastCalledWith('/api/app-key/rotation/ap3/retry')
})

test('a job that ends done says so and refreshes the key', async () => {
  const client = renderRotation(job('running', [{ router_id: 'ap2', name: 'AP2 · office', state: 'removing', detail: null }]))
  const spy = vi.spyOn(client, 'invalidateQueries')
  act(() => client.setQueryData(['app-key-rotation'], job('done', [{ router_id: 'ap2', name: 'AP2 · office', state: 'moved', detail: null }])))
  expect(await screen.findByText('Rotated: every router logs in with the new key. The old private key is deleted.')).toBeInTheDocument()
  await vi.waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['app-key'] }))
})

test('a done job names routers that still accept the old key', () => {
  renderRotation(
    job('done', [
      { router_id: 'ap1', name: 'AP1 · bench', state: 'moved', detail: null },
      { router_id: 'ap2', name: 'AP2 · office', state: 'moved', detail: 'the old key is still accepted by 1 other line: remove it on System › Access' },
    ]),
  )
  expect(screen.getByRole('status')).toHaveTextContent(
    'Rotated: every router logs in with the new key. The old private key is deleted. AP2 · office still accepts the old key in another line: see below.',
  )
})

test('a harness run shows the guard text', async () => {
  const user = userEvent.setup()
  vi.mocked(postJson)
    .mockResolvedValueOnce(PREVIEW)
    .mockRejectedValueOnce(new ApiError(423, 'Bench Guard: dima_night.py runs', { detail: 'Bench Guard: dima_night.py runs' }))
  renderRotation()
  await user.click(screen.getByRole('button', { name: 'Rotate key…' }))
  await user.click(screen.getByRole('button', { name: 'Start' }))
  expect(screen.getByRole('alert')).toHaveTextContent('Bench Guard: dima_night.py runs')
})
