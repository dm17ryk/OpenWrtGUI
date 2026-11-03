import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { expect, test } from 'vitest'
import type { RouterDetail } from '../api/types'
import { AP2, SUMMARY } from '../testing/fixtures'
import { RouterOverview } from './RouterOverview'

function renderOverview(detail: RouterDetail) {
  const client = new QueryClient()
  client.setQueryData(['router', 'ap2'], detail)
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

test('router without a key explains why there is no description', () => {
  renderOverview({ ...AP2, record: { ...AP2.record, auth: 'none' }, summary: null, status: null })
  expect(screen.getByText(/needs the app key/)).toBeInTheDocument()
})
