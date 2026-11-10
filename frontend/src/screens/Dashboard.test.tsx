import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, test, vi } from 'vitest'
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

afterEach(() => {
  vi.unstubAllGlobals()
})

test('a lost connection shows the plain message, not an error class name', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }),
  )
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect(
    await screen.findByText(
      'Could not load the routers: Lost the connection to OpenWrtGUI. The app may have closed. Start it again.',
    ),
  ).toBeInTheDocument()
})

test('headline, air map, cards, attention and the router list offer help from the manual', async () => {
  renderWith(ROUTERS)
  for (const name of ['Help: Headline', 'Help: Needs attention', 'Help: Router list']) {
    expect(screen.getByRole('button', { name })).toBeInTheDocument()
  }
  expect(screen.getAllByRole('button', { name: 'Help: Air map' }).length).toBeGreaterThan(0)
  const card = screen.getByRole('article', { name: 'AP2 · office' })
  await userEvent.setup().hover(within(card).getByText('parked'))
  expect(await screen.findByRole('tooltip')).toHaveTextContent('One card per router, with a state badge')
})

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

const SUMMARY_AP1 = { profile: 'dlink,dwr-921-c3-uboot r35692-b8bffeefdf', files_added: 3, packages_added: 1, configs_changed: 2, owners: [], reflash_pending: false }

test('lists files added after flashing in Needs attention', () => {
  renderWith([{ ...AP1, discovery: SUMMARY_AP1 }, AP2])
  const attention = screen.getByRole('region', { name: 'Needs attention' })
  expect(within(attention).getByText(/3 files added after flashing/)).toBeInTheDocument()
  expect(within(attention).getByRole('link', { name: 'Open Discovery' })).toHaveAttribute('href', '/routers/ap1/discovery')
})

test('a router reflashed without settings is to be added again', () => {
  const reflashed = { ...AP2, record: { ...AP2.record, reflashed: { board: 'dlink,dwr-921-c3-uboot', revision: 'r35700-0c0ffee000', at: '2026-11-08T12:00:00', reason: 'flash' as const } } }
  renderWith([AP1, reflashed])
  const attention = screen.getByRole('region', { name: 'Needs attention' })
  expect(within(attention).getByText(/Reflashed without settings: add it again/)).toBeInTheDocument()
  expect(within(attention).getByRole('link', { name: 'Add again' })).toHaveAttribute('href', '/add?host=192.168.1.1')
})

test('shows owner tags on the router card', () => {
  renderWith([{ ...AP1, discovery: { ...SUMMARY_AP1, owners: ['BENCHSIPGUARD · dima_night'] } }, AP2])
  const card = screen.getByRole('article', { name: 'AP1 · bench' })
  expect(within(card).getByText('BENCHSIPGUARD · dima_night')).toBeInTheDocument()
})

test('a router card shows the faults armed on it and links to them', () => {
  const armed = { ...AP1, status: AP1.status && { ...AP1.status, faults_armed: 1 } }
  renderWith([armed, AP2])
  const card = screen.getByRole('article', { name: 'AP1 · bench' })
  expect(within(card).getByRole('link', { name: '1 fault armed' })).toHaveAttribute('href', '/routers/ap1/faults')
  expect(within(screen.getByRole('article', { name: 'AP2 · office' })).queryByText(/armed/)).toBeNull()
})
