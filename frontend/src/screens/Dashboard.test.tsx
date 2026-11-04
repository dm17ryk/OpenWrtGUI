import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { expect, test } from 'vitest'
import type { RouterItem } from '../api/types'
import { AP1, AP2, ROUTERS } from '../testing/fixtures'
import { Dashboard } from './Dashboard'

function renderWith(items: RouterItem[]) {
  const client = new QueryClient()
  client.setQueryData(['routers'], items)
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('heading counts routers, radios on air and stations', () => {
  renderWith(ROUTERS)
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('3 routers · 1 radio on air · 1 station')
})

test('AP2 shows parked and its staged channel', () => {
  renderWith(ROUTERS)
  const card = screen.getByRole('article', { name: 'AP2 · office' })
  expect(within(card).getByText('parked')).toBeInTheDocument()
  const air = screen.getByRole('region', { name: '2.4 GHz air' })
  expect(within(air).getByText('staged ch 1 · HT40 · radio off')).toBeInTheDocument()
})

test('air map bars carry their full text as a tooltip for narrow screens', () => {
  renderWith(ROUTERS)
  const air = screen.getByRole('region', { name: '2.4 GHz air' })
  expect(within(air).getByText('staged ch 1 · HT40 · radio off')).toHaveAttribute('title', 'staged ch 1 · HT40 · radio off')
})

test('a router on air shows its station', () => {
  renderWith(ROUTERS)
  const card = screen.getByRole('article', { name: 'AP1 · bench' })
  expect(within(card).getByText('on air')).toBeInTheDocument()
  expect(within(card).getByText(/1 station/)).toBeInTheDocument()
  expect(within(card).getByText(/−52 dBm · TX 65 · RX 54/)).toBeInTheDocument()
  expect(within(card).getByText('lan 192.168.1.1/24 · DHCP server on')).toBeInTheDocument()
})

test('router without key is in Needs attention', () => {
  renderWith(ROUTERS)
  const attention = screen.getByRole('region', { name: 'Needs attention' })
  expect(within(attention).getByText('AP3 · QA stands')).toBeInTheDocument()
  expect(within(attention).getByText(/no app key yet/)).toBeInTheDocument()
})

test('unreachable router is reported with the time', () => {
  const down: RouterItem = { ...AP2, status: null, health: { online: false, since: '2026-11-03T12:34:00', error: 'timed out' } }
  renderWith([AP1, down])
  const attention = screen.getByRole('region', { name: 'Needs attention' })
  expect(within(attention).getByText(/unreachable since 12:34/)).toBeInTheDocument()
  expect(within(screen.getByRole('article', { name: 'AP2 · office' })).getByText('unreachable')).toBeInTheDocument()
})

test('only the 2.4 GHz block is drawn for 2g-only routers', () => {
  renderWith(ROUTERS)
  expect(screen.getByRole('heading', { name: '2.4 GHz air' })).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: '5 GHz air' })).toBeNull()
})
