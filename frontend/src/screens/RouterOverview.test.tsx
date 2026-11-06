import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { expect, test } from 'vitest'
import type { RouterDetail } from '../api/types'
import { AP2, SUMMARY } from '../testing/fixtures'
import { LUCI_PAGES } from '../testing/luci'
import { RouterOverview } from './RouterOverview'

function renderOverview(detail: RouterDetail) {
  const client = new QueryClient()
  client.setQueryData(['router', 'ap2'], detail)
  client.setQueryData(['luci-pages', 'ap2'], LUCI_PAGES)
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/routers/ap2']}>
        <Routes>
          <Route path="/routers/:id" element={<RouterOverview />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('the overview and its sections offer help from the manual', () => {
  renderOverview({ ...AP2, summary: SUMMARY })
  expect(screen.getByRole('button', { name: 'Help: Router overview' })).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'What AP2 says about itself' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Help: 5. What is this router, and its sockets' })).toBeInTheDocument()
})

test('overview shows 155 radio and 289 SSID options', () => {
  renderOverview({ ...AP2, summary: SUMMARY })
  const wifi = screen.getByRole('article', { name: 'network.wireless get_validate' })
  expect(within(wifi).getByText(/radio 155 · SSID 289 · station 4 · VLAN 9/)).toBeInTheDocument()
})

test('overview lists the six sources and the port labels', () => {
  renderOverview({ ...AP2, summary: SUMMARY })
  for (const name of [
    '/etc/board.json',
    'ubus -v list',
    'network.wireless get_validate',
    'network get_proto_handlers',
    'luci getFeatures',
    'LuCI menu and ACL files',
  ]) {
    expect(screen.getByRole('article', { name })).toBeInTheDocument()
  }
  expect(screen.getByText('5 LuCI packages, 62 menu entries')).toBeInTheDocument()
  expect(screen.getByRole('cell', { name: 'LAN4' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('AP2 · office')
})

test('the LuCI pages card links each page to its screen here or to LuCI', () => {
  renderOverview({ ...AP2, summary: SUMMARY })
  const card = screen.getByRole('region', { name: 'LuCI pages on AP2' })
  const wireless = within(card).getByRole('row', { name: /Wireless/ })
  expect(within(wireless).getByText('luci-mod-network')).toBeInTheDocument()
  expect(within(wireless).getByRole('link', { name: 'Wi-Fi' })).toHaveAttribute('href', '/routers/ap2/wifi')
  const zones = within(card).getByRole('row', { name: /General Settings/ })
  expect(within(zones).getByRole('link', { name: 'Firewall' })).toHaveAttribute('href', '/routers/ap2/firewall')
  const dhcp = within(card).getByRole('row', { name: /DHCP/ })
  expect(within(dhcp).getByText('Network › DHCP')).toBeInTheDocument()
  expect(within(dhcp).getByText('no screen here yet')).toBeInTheDocument()
  expect(within(dhcp).getByRole('link', { name: 'Open Network › DHCP in LuCI' })).toHaveAttribute(
    'href',
    '/routers/ap2/luci?page=admin%2Fnetwork%2Fdhcp',
  )
  expect(within(card).getByText('Status › Firewall (iptables)')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Help: Which pages open here' })).toBeInTheDocument()
})

test('router without a key explains why there is no description', () => {
  renderOverview({ ...AP2, record: { ...AP2.record, auth: 'none' }, summary: null, status: null })
  expect(screen.getByText(/needs the app key/)).toBeInTheDocument()
})
