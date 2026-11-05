import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { expect, test } from 'vitest'
import { RouterSections, type LuciPageLink, type Section } from './RouterSections'

const PAGES: LuciPageLink[] = [
  { path: 'admin/network/wireless', title: 'Wireless', native: 'wifi' },
  { path: 'admin/services/sqm', title: 'SQM QoS', native: null },
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

test('lists the router screens and the LuCI pages with no screen here', () => {
  const nav = renderSections('wifi')
  const links = within(nav).getAllByRole('link')
  expect(links.map((a) => a.textContent)).toEqual(['Overview', 'Wi-Fi', 'RF live', 'Terminal', 'LuCI: SQM QoS'])
  expect(within(nav).getByRole('link', { name: 'Wi-Fi' })).toHaveAttribute('aria-current', 'page')
  expect(within(nav).getByRole('link', { name: 'Overview' })).not.toHaveAttribute('aria-current')
  expect(within(nav).getByRole('link', { name: 'RF live' })).toHaveAttribute('href', '/routers/ap2/rf')
  expect(within(nav).getByRole('link', { name: 'LuCI: SQM QoS' })).toHaveAttribute(
    'href',
    '/routers/ap2/luci?page=admin%2Fservices%2Fsqm',
  )
})

test('the open LuCI page is the current one', () => {
  const nav = renderSections('luci', 'admin/services/sqm')
  expect(within(nav).getByRole('link', { name: 'LuCI: SQM QoS' })).toHaveAttribute('aria-current', 'page')
})
