import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { expect, test } from 'vitest'
import type { LuciPageView } from '../api/types'
import { RouterSections, type Section } from './RouterSections'

const PAGES: LuciPageView[] = [
  { path: 'admin/network/wireless', title: 'Wireless', package: 'luci-mod-network', native: 'wifi', section: 'Network', label: 'Network › Wireless' },
  { path: 'admin/services/sqm', title: 'SQM QoS', package: 'luci-app-sqm', native: null, section: 'Services', label: 'Services › SQM QoS' },
]

function renderSections(current: Section, luciPath?: string) {
  const client = new QueryClient()
  client.setQueryData(['luci-pages', 'ap2'], PAGES)
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RouterSections routerId="ap2" name="AP2 · office" current={current} luciPath={luciPath} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return screen.getByRole('navigation', { name: 'AP2 sections' })
}

test('lists the router screens and folds the LuCI pages into one list', async () => {
  const user = userEvent.setup()
  const nav = renderSections('wifi')
  const own = within(nav).getAllByRole('link').filter((a) => !a.closest('details'))
  expect(own.map((a) => a.textContent)).toEqual(['Overview', 'Wi-Fi', 'RF live', 'Terminal'])
  expect(within(nav).getByRole('link', { name: 'Wi-Fi' })).toHaveAttribute('aria-current', 'page')
  expect(within(nav).getByRole('link', { name: 'Overview' })).not.toHaveAttribute('aria-current')
  expect(within(nav).getByRole('link', { name: 'RF live' })).toHaveAttribute('href', '/routers/ap2/rf')
  const more = within(nav).getByText('LuCI pages (1)')
  expect(more.closest('details')).not.toHaveAttribute('open')
  await user.click(more)
  expect(more.closest('details')).toHaveAttribute('open')
  expect(within(nav).getByRole('link', { name: 'Services › SQM QoS' })).toHaveAttribute(
    'href',
    '/routers/ap2/luci?page=admin%2Fservices%2Fsqm',
  )
})

test('the open LuCI page is the current one', () => {
  const nav = renderSections('luci', 'admin/services/sqm')
  const current = within(nav).getByRole('link', { name: 'LuCI: Services › SQM QoS' })
  expect(current).toHaveAttribute('aria-current', 'page')
  expect(current.closest('details')).toBeNull()
})

test('no LuCI list when every page has a screen here', () => {
  const client = new QueryClient()
  client.setQueryData(['luci-pages', 'ap2'], [PAGES[0]])
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RouterSections routerId="ap2" name="AP2 · office" current="overview" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect(screen.queryByText(/LuCI pages/)).not.toBeInTheDocument()
})
