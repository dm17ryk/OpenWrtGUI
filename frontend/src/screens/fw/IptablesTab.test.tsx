import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { AP4_IPTABLES, AP4_RESET_PLAN } from '../../testing/later'
import { IptablesTab } from './IptablesTab'

const base = '/api/routers/ap4/firewall/iptables'

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path === base) return AP4_IPTABLES
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string) => {
      if (path === `${base}/reset/preview`) return AP4_RESET_PLAN
      throw new Error(`unexpected ${path}`)
    }),
  }
})

function renderTab() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <IptablesTab routerId="ap4" short="AP4" />
    </QueryClientProvider>,
  )
}

test('the chains and rules of the chosen table', async () => {
  renderTab()
  expect(await screen.findByText('Chain INPUT')).toBeInTheDocument()
  expect(screen.getByText('Drop SSH from the lab net')).toBeInTheDocument()
  expect(screen.getByText('Policy ACCEPT · 1200 packets')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Help: Legacy iptables' })).toBeInTheDocument()
})

test('empty chains hide on request, and a reset says what it covers', async () => {
  const user = userEvent.setup()
  renderTab()
  await user.click(await screen.findByLabelText('Hide empty chains'))
  expect(screen.queryByText('Chain lab_user')).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Reset counters' }))
  expect(await screen.findByText(/filter table's counters only/)).toBeInTheDocument()
})
