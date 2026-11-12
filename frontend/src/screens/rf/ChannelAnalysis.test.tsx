import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import type { Bss, ScanPlanOut, ScanResult } from '../../api/types'
import { ChannelAnalysis } from './ChannelAnalysis'
import { ChannelChart, STEP } from './ChannelChart'

const calls: Array<{ path: string; body: unknown }> = []
const PLAN: ScanPlanOut = {
  via: 'ap',
  lines: ['iw dev phy0-ap0 scan ap-force passive'],
  warnings: ['Stations on OpenWrt may miss up to about 2 s of traffic during the scan.'],
  digest: 'feedfacecafe0003',
}
const net = (over: Partial<Bss>): Bss => ({
  bssid: '02:00:00:00:a0:01',
  ssid: 'net-01',
  freq_mhz: 2412,
  channel: 1,
  signal_dbm: -48,
  width_mhz: 20,
  secondary: null,
  security: 'WPA2',
  last_seen_ms: 160,
  own: false,
  ...over,
})
const RESULT: ScanResult = {
  router_id: 'ap1',
  radio: 'radio0',
  at: '2026-11-12T10:00:05',
  via: 'ap',
  seconds: 1.6,
  networks: [
    net({ bssid: '02:00:00:00:00:01', ssid: 'OpenWrt', freq_mhz: 2437, channel: 6, signal_dbm: -20, own: true }),
    net({}),
    net({ bssid: '02:00:00:00:a0:02', ssid: null, freq_mhz: 2422, channel: 3, signal_dbm: -71 }),
    net({ bssid: '02:00:00:00:a0:05', ssid: 'net-05', freq_mhz: 2462, channel: 11, width_mhz: 40, secondary: 'below', signal_dbm: -58 }),
  ],
  channels: Array.from({ length: 13 }, (_, i) => ({
    channel: i + 1,
    freq_mhz: 2412 + 5 * i,
    busy_pct: i === 5 ? 42.5 : 20,
    networks: i === 0 ? 1 : 0,
    strongest_dbm: i === 0 ? -48 : null,
  })),
}
let last: ScanResult | null = null

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  const respond = async (path: string, body?: unknown): Promise<unknown> => {
    calls.push({ path, body })
    const base = '/api/routers/ap1/rf/radio0/scan'
    if (path === base && body === undefined) return last
    if (path === `${base}/preview`) return PLAN
    if (path === base) {
      last = RESULT
      return RESULT
    }
    throw new Error(`unexpected ${path}`)
  }
  return { ...actual, apiFetch: vi.fn((p: string) => respond(p)), postJson: vi.fn((p: string, b?: unknown) => respond(p, b)) }
})

beforeEach(() => {
  calls.length = 0
  last = null
})

function renderScan() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ChannelAnalysis routerId="ap1" radio="radio0" />
    </QueryClientProvider>,
  )
}

test('scan preview then result table', async () => {
  const user = userEvent.setup()
  renderScan()
  const card = await screen.findByRole('region', { name: 'Channel analysis' })
  await user.click(within(card).getByRole('button', { name: 'Scan…' }))
  const code = await within(card).findByRole('region', { name: 'Command preview' })
  expect(code).toHaveTextContent('iw dev phy0-ap0 scan ap-force passive')
  expect(within(card).getByText(/may miss up to about 2 s/)).toBeInTheDocument()
  await user.click(within(card).getByRole('button', { name: 'Scan now' }))
  await waitFor(() => expect(calls.some((c) => c.path.endsWith('/scan') && c.body !== undefined)).toBe(true))
  expect(calls.find((c) => c.path.endsWith('/scan') && c.body !== undefined)?.body).toEqual({ digest: PLAN.digest })
  const table = await within(card).findByRole('table', { name: 'Networks heard' })
  expect(within(table).getAllByRole('row')).toHaveLength(5)
  expect(within(card).getByText(/Last scan .* via the AP interface/)).toBeInTheDocument()
})

test('hidden and own networks labelled', async () => {
  last = RESULT
  renderScan()
  const table = await screen.findByRole('table', { name: 'Networks heard' })
  expect(within(table).getByText('(hidden)')).toBeInTheDocument()
  const own = within(table).getByText('OpenWrt').closest('tr')
  expect(own).not.toBeNull()
  expect(within(own as HTMLElement).getByText('own')).toBeInTheDocument()
})

test('no networks heard', async () => {
  last = { ...RESULT, networks: [] }
  renderScan()
  expect(await screen.findByText('No networks heard.')).toBeInTheDocument()
})

test('chart draws a 40 MHz span twice as wide as a 20 MHz one', () => {
  render(<ChannelChart result={RESULT} />)
  const wide = screen.getByTestId('span-02:00:00:00:a0:05')
  const narrow = screen.getByTestId('span-02:00:00:00:a0:01')
  expect(Number(wide.getAttribute('width'))).toBe(8 * STEP)
  expect(Number(narrow.getAttribute('width'))).toBe(4 * STEP)
  expect(screen.getByRole('img', { name: /13 channels, 4 networks/ })).toBeInTheDocument()
})
