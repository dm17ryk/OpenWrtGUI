import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { expect, test } from 'vitest'
import type { LuciPageView } from '../../api/types'
import { LuciPagesCard } from './LuciPagesCard'

const PAGES: LuciPageView[] = [
  { path: 'admin/system/plugins', title: 'Plugins', package: 'luci-mod-system', native: null, section: 'System', label: 'System › Plugins', available: true, checked: true },
  { path: 'admin/status/realtime/wireless', title: 'Wireless', package: 'luci-mod-status', native: 'rf', section: 'Status › Realtime Graphs', label: 'Status › Realtime Graphs › Wireless', available: true, checked: true },
  { path: 'admin/system/mounts', title: 'Mount Points', package: 'luci-mod-system', native: null, section: 'System', label: 'System › Mount Points', available: false, missing: 'needs /sbin/block', checked: true },
]

function renderCard() {
  const client = new QueryClient()
  client.setQueryData(['luci-pages', 'ap2'], PAGES)
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <LuciPagesCard routerId="ap2" short="AP2" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return screen.getByRole('region', { name: 'LuCI pages on AP2' })
}

test('a page LuCI would not show here is listed apart, with why', () => {
  const card = renderCard()
  expect(within(card).getByRole('link', { name: 'Open System › Plugins in LuCI' })).toBeInTheDocument()
  expect(within(card).queryByRole('link', { name: 'Open System › Mount Points in LuCI' })).not.toBeInTheDocument()
  const lacking = within(card).getByText('Not on this router (1)')
  expect(lacking.closest('details')).not.toHaveAttribute('open')
  const list = within(card).getByRole('list', { name: 'LuCI pages not on AP2' })
  expect(list).toHaveTextContent('System › Mount Points: needs /sbin/block')
})

test('Realtime Graphs › Wireless links to RF live', () => {
  const card = renderCard()
  expect(within(card).getByRole('link', { name: 'RF live' })).toHaveAttribute('href', '/routers/ap2/rf')
})
