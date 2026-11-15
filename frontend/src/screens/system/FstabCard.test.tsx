import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import type { FstabState } from '../../api/types'
import { AP4_FSTAB, AP4_FSTAB_OFF_PLAN } from '../../testing/later'
import { FstabCard } from './FstabCard'

const calls: Array<{ path: string; body: unknown }> = []
const base = '/api/routers/ap4/system/fstab'

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    postJson: vi.fn(async (path: string, body?: unknown) => {
      calls.push({ path, body })
      if (path === `${base}/preview`) return AP4_FSTAB_OFF_PLAN
      throw new Error(`unexpected ${path}`)
    }),
  }
})

beforeEach(() => {
  calls.length = 0
})

function renderCard(state: FstabState) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <FstabCard routerId="ap4" short="AP4" state={state} />
    </QueryClientProvider>,
  )
}

test('the settings and each entry with its device', () => {
  renderCard(AP4_FSTAB)
  expect(screen.getByLabelText('Mount automatically (auto_mount)')).toBeChecked()
  expect(screen.getByDisplayValue('/mnt/usb')).toBeInTheDocument()
  expect(screen.getAllByText('/dev/sda1 · usb · ext4').length).toBeGreaterThan(0)
  expect(screen.getByRole('button', { name: 'Add mount' })).toBeEnabled()
})

test('a device that is not there is marked', () => {
  renderCard({ ...AP4_FSTAB, devices: [] })
  expect(screen.getAllByText('not present')).toHaveLength(2)
})

test('an entry turned off is previewed with the whole list', async () => {
  const user = userEvent.setup()
  renderCard(AP4_FSTAB)
  await user.click(screen.getAllByLabelText('Enabled')[0])
  const preview = await screen.findByRole('region', { name: 'Command preview' })
  expect(preview).toHaveTextContent("uci set fstab.cfg02a7f1.enabled='0'")
  const body = calls.at(-1)?.body as { entries: Array<{ section: string | null; enabled: boolean }> }
  expect(body.entries.map((e) => [e.section, e.enabled])).toEqual([
    ['cfg02a7f1', false],
    ['cfg03a7f1', false],
  ])
})
