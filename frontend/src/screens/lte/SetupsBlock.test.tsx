import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { LteSetupSummary } from '../../api/types'
import { LTE_APN_PLAN, LTE_SETTINGS_RESULT } from '../../testing/lte'
import { SetupsBlock } from './SetupsBlock'

const calls: Array<{ path: string; body: unknown }> = []
let setups: LteSetupSummary[] = []

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path === '/api/lte-setups') return setups
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body?: unknown) => {
      calls.push({ path, body })
      if (path === '/api/routers/ap2/lte/setup') return OWN
      if (path === '/api/routers/ap2/lte/setup/preview') return LTE_APN_PLAN
      if (path === '/api/routers/ap2/lte/setup/apply') return LTE_SETTINGS_RESULT
      throw new Error(`unexpected ${path}`)
    }),
  }
})

const OWN: LteSetupSummary = {
  router_id: 'ap2',
  router_name: 'AP2 · office',
  saved_at: '2026-11-10T09:00:00+02:00',
  apn: 'test-apn',
  pdptype: 'ipv4',
  readable: true,
}
const OTHER: LteSetupSummary = { ...OWN, router_id: 'ap1', router_name: 'AP1 · lab', saved_at: '2026-11-12T09:00:00+02:00' }
const BROKEN: LteSetupSummary = { router_id: 'ap3', router_name: 'ap3', saved_at: null, apn: null, pdptype: null, readable: false }

beforeEach(() => {
  calls.length = 0
  setups = []
})
afterEach(() => vi.unstubAllGlobals())

function show(works: boolean) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <SetupsBlock routerId="ap2" works={works} onApplied={() => {}} />
    </QueryClientProvider>,
  )
}

test('Save good setup waits until LTE works', async () => {
  show(false)
  const save = await screen.findByRole('button', { name: 'Save good setup' })
  expect(save).toBeDisabled()
  expect(save).toHaveAttribute('title', 'Save a good setup while LTE works')
})

test('Save good setup posts the save when LTE works', async () => {
  const user = userEvent.setup()
  show(true)
  await user.click(await screen.findByRole('button', { name: 'Save good setup' }))
  expect(calls).toEqual([{ path: '/api/routers/ap2/lte/setup', body: undefined }])
})

test('replacing an older setup asks first', async () => {
  const user = userEvent.setup()
  setups = [OWN]
  const confirm = vi.fn(() => false)
  vi.stubGlobal('confirm', confirm)
  show(true)
  await screen.findByRole('option', { name: /This router's good setup/ })
  await user.click(screen.getByRole('button', { name: 'Save good setup' }))
  expect(confirm).toHaveBeenCalledWith('Replace the good setup saved 2026-11-10?')
  expect(calls).toEqual([])
})

test('Reconfigure lists this router first, then the others, and previews then applies', async () => {
  const user = userEvent.setup()
  setups = [OTHER, BROKEN, OWN]
  show(false)
  const source = await screen.findByRole('combobox', { name: 'Reconfigure from' })
  await screen.findByRole('option', { name: /This router's good setup/ })
  const options = screen.getAllByRole('option').map((o) => o.textContent)
  expect(options).toEqual([
    'Choose a saved setup…',
    "This router's good setup, saved 2026-11-10",
    'AP1 · lab, saved 2026-11-12 (not its SIM PIN)',
    'ap3 (cannot be read)',
  ])
  expect(screen.getByRole('option', { name: 'ap3 (cannot be read)' })).toBeDisabled()
  await user.selectOptions(source, 'ap1')
  expect(await screen.findByRole('region', { name: 'Command preview' })).toBeInTheDocument()
  expect(calls.at(-1)).toEqual({ path: '/api/routers/ap2/lte/setup/preview', body: { source: 'ap1' } })
  await user.click(screen.getByRole('button', { name: /^Apply/ }))
  expect(calls.at(-1)).toEqual({ path: '/api/routers/ap2/lte/setup/apply', body: { source: 'ap1', digest: LTE_APN_PLAN.digest } })
})
