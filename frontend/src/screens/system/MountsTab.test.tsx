import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { AP2_MOUNTS } from '../../testing/system'
import { MountsTab } from './MountsTab'

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path === '/api/routers/ap2/system/mounts') return AP2_MOUNTS
      throw new Error(`unexpected ${path}`)
    }),
  }
})

test('the mounted file systems with their usage, and the block-mount note', async () => {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MountsTab routerId="ap2" />
    </QueryClientProvider>,
  )
  const table = await screen.findByRole('table', { name: 'Mount points' })
  expect(within(table).getAllByRole('row')).toHaveLength(AP2_MOUNTS.mounts.length + 1)
  const overlay = within(table).getByRole('row', { name: /^\/overlay / })
  expect(overlay).toHaveTextContent('/dev/mtdblock6')
  expect(overlay).toHaveTextContent('jffs2')
  expect(overlay).toHaveTextContent('8%')
  expect(screen.getByText('fstab editing needs the block-mount package, which this image does not have.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Help: Mount points' })).toBeInTheDocument()
})
