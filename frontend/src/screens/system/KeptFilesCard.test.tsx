import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { AP2_KEPT, AP2_KEPT_PLAN } from '../../testing/system'
import { KeptFilesCard } from './KeptFilesCard'

const base = '/api/routers/ap2/system/kept-files'
const calls: Array<{ path: string; body: unknown }> = []

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path === base) return AP2_KEPT
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body?: unknown) => {
      calls.push({ path, body })
      if (path === `${base}/preview`) return AP2_KEPT_PLAN
      throw new Error(`unexpected ${path}`)
    }),
  }
})

beforeEach(() => {
  calls.length = 0
})

test('the kept-files list is edited as text beside what a backup holds now', async () => {
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <KeptFilesCard routerId="ap2" short="AP2" />
    </QueryClientProvider>,
  )
  const text = await screen.findByRole('textbox', { name: 'Files kept in a backup (/etc/sysupgrade.conf)' })
  expect(text).toHaveValue(AP2_KEPT.text)
  const held = screen.getByRole('list', { name: 'Files a backup holds' })
  expect(within(held).getAllByRole('listitem').map((li) => li.textContent)).toEqual(AP2_KEPT.listed)
  await user.click(text)
  await user.keyboard('{Control>}{End}{/Control}/etc/owg-extra.conf{Enter}')
  expect(await screen.findByRole('region', { name: 'Command preview' })).toHaveTextContent("cat > /etc/sysupgrade.conf <<'OWG'")
  expect(calls.at(-1)).toEqual({ path: `${base}/preview`, body: { text: `${AP2_KEPT.text}/etc/owg-extra.conf\n` } })
})
