import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { expect, test } from 'vitest'
import type { LuciPageView } from '../api/types'
import { RouterSections, type Section } from './RouterSections'

const PAGES: LuciPageView[] = [
  { path: 'admin/network/wireless', title: 'Wireless', package: 'luci-mod-network', native: 'wifi', section: 'Network', label: 'Network › Wireless', available: true, checked: true },
  { path: 'admin/services/sqm', title: 'SQM QoS', package: 'luci-app-sqm', native: null, section: 'Services', label: 'Services › SQM QoS', available: true, checked: true },
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
  expect(own.map((a) => a.textContent)).toEqual([
    'Overview',
    'Discovery',
    'Wi-Fi',
    'RF live',
    'Network & DHCP',
    'LTE',
    'Ports & VLANs',
    'Firewall',
    'Faults & capture',
    'System',
    'Terminal',
  ])
  expect(within(nav).getByRole('link', { name: 'System' })).toHaveAttribute('href', '/routers/ap2/system')
  expect(within(nav).getByRole('link', { name: 'Ports & VLANs' })).toHaveAttribute('href', '/routers/ap2/ports')
  expect(within(nav).getByRole('link', { name: 'Firewall' })).toHaveAttribute('href', '/routers/ap2/firewall')
  expect(within(nav).getByRole('link', { name: 'Wi-Fi' })).toHaveAttribute('aria-current', 'page')
  expect(within(nav).getByRole('link', { name: 'Overview' })).not.toHaveAttribute('aria-current')
  expect(within(nav).getByRole('link', { name: 'RF live' })).toHaveAttribute('href', '/routers/ap2/rf')
  expect(within(nav).getByRole('link', { name: 'LTE' })).toHaveAttribute('href', '/routers/ap2/lte')
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

test('pages this router lacks are not in the LuCI list', () => {
  const client = new QueryClient()
  client.setQueryData(['luci-pages', 'ap2'], [
    ...PAGES,
    { path: 'admin/system/mounts', title: 'Mount Points', package: 'luci-mod-system', native: null, section: 'System', label: 'System › Mount Points', available: false, missing: 'needs /sbin/block', checked: true },
  ])
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RouterSections routerId="ap2" name="AP2 · office" current="overview" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect(screen.getByText('LuCI pages (1)')).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'System › Mount Points' })).not.toBeInTheDocument()
})
