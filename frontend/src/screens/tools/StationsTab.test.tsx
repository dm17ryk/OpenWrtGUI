import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { ActionResult, StationsView } from '../../api/types'
import { StationsTab } from './StationsTab'

const MAC = '02:00:00:00:00:30'
const OWN = { bssid: '02:00:00:00:00:01', ssid: 'OwgTest', nr: '0200000000010000', source: 'AP2 · OwgTest' }
const OTHER = { bssid: '02:00:00:00:00:03', ssid: 'OwgTest', nr: '0200000000030000', source: 'AP3 · OwgTest' }
const FIVE = ['bss_transition_request', 'rrm_nr_get_own', 'rrm_nr_list', 'rrm_nr_set', 'rrm_beacon_req']
const RUNTIME = 'Kept until the next Wi-Fi reload: hostapd does not save it.'
const NOT_SUPPORTED =
  'hostapd on AP2 says Not supported. BSS transition needs bss_transition on this SSID: Wi-Fi › All options › bss_transition.'

const posts: Array<[string, unknown]> = []
let view: StationsView
let result: ActionResult

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path === '/api/routers/ap2/tools/stations') return view
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body: unknown) => {
      posts.push([path, body])
      const kind = (body as { kind: string }).kind
      if (path.endsWith('/stations/preview')) {
        const lines = [`ubus call hostapd.phy0-ap0 ${kind}`]
        if (kind !== 'neighbours') lines.push("timeout -s KILL 12 ubus subscribe hostapd.phy0-ap0  # 10 s, for the station's answer")
        return { lines, warnings: kind === 'neighbours' ? [RUNTIME] : [], digest: `d-${kind}` }
      }
      if (path.endsWith('/stations/apply')) return result
      throw new Error(`unexpected ${path}`)
    }),
  }
})

function stationsView(methods: string[] = FIVE): StationsView {
  return {
    aps: [
      {
        ifname: 'phy0-ap0',
        ssid: 'OwgTest',
        channel: 11,
        methods,
        own: OWN,
        neighbours: [OWN],
        stations: [{ mac: MAC, name: 'phone', ip: '192.168.1.30', signal_dbm: -48 }],
      },
    ],
    candidates: [OWN, OTHER],
    notes: [],
  }
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  posts.length = 0
  view = stationsView()
  result = { ok: true, detail: 'The station answered the BSS transition request (status 0).', events: [], beacons: [], status_code: 0 }
})

afterEach(() => {
  vi.useRealTimers()
})

function show() {
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <StationsTab routerId="ap2" />
    </QueryClientProvider>,
  )
  return user
}

test('one section per AP, with its stations', async () => {
  show()
  const ap = await screen.findByRole('region', { name: 'OwgTest (phy0-ap0, channel 11)' })
  expect(within(ap).getByText(MAC)).toBeInTheDocument()
  expect(within(ap).getByRole('button', { name: `BSS transition request to ${MAC}` })).toBeInTheDocument()
  expect(within(ap).getByRole('button', { name: `Beacon report request to ${MAC}` })).toBeInTheDocument()
})

test('a BSS transition request to a chosen candidate, previewed and applied', async () => {
  const user = show()
  const ap = await screen.findByRole('region', { name: 'OwgTest (phy0-ap0, channel 11)' })
  await user.selectOptions(within(ap).getByLabelText(`Target for ${MAC}`), OTHER.bssid)
  await user.click(within(ap).getByRole('button', { name: `BSS transition request to ${MAC}` }))
  expect(await within(ap).findByText(/ubus call hostapd.phy0-ap0 transition/)).toBeInTheDocument()
  await user.click(within(ap).getByRole('button', { name: 'Apply' }))
  expect(posts).toContainEqual([
    '/api/routers/ap2/tools/stations/apply',
    { kind: 'transition', ifname: 'phy0-ap0', mac: MAC, target: OTHER.bssid, neighbours: [], digest: 'd-transition' },
  ])
  expect(await within(ap).findByText('The station answered the BSS transition request (status 0).')).toBeInTheDocument()
  expect(within(ap).getByText('Status code 0')).toBeInTheDocument()
})

test('a beacon report shows its table', async () => {
  result = {
    ok: true,
    detail: 'The station sent 1 beacon report.',
    events: [],
    beacons: [{ bssid: '02:00:00:00:00:03', channel: 11, rcpi_dbm: -50, rsni: 40 }],
    status_code: null,
  }
  const user = show()
  const ap = await screen.findByRole('region', { name: 'OwgTest (phy0-ap0, channel 11)' })
  await user.click(within(ap).getByRole('button', { name: `Beacon report request to ${MAC}` }))
  await within(ap).findByText(/ubus call hostapd.phy0-ap0 beacon/)
  await user.click(within(ap).getByRole('button', { name: 'Apply' }))
  const table = await within(ap).findByRole('table', { name: 'Beacon report' })
  expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['BSSID', 'Channel', 'Signal (dBm)', 'RSNI'])
  expect(within(table).getAllByRole('cell').map((c) => c.textContent)).toEqual(['02:00:00:00:00:03', '11', '-50', '40'])
})

test('the neighbour report: its list, set from the candidates, and Clear', async () => {
  const user = show()
  const ap = await screen.findByRole('region', { name: 'OwgTest (phy0-ap0, channel 11)' })
  const nr = within(ap).getByRole('group', { name: 'Set from the routers in this app' })
  expect(within(ap).getByText(`${OWN.bssid} ${OWN.ssid}`)).toBeInTheDocument()
  await user.click(within(nr).getByRole('checkbox', { name: `${OTHER.source} (${OTHER.bssid})` }))
  await user.click(within(ap).getByRole('button', { name: 'Set neighbour report' }))
  expect(await within(ap).findByText(RUNTIME)).toBeInTheDocument()
  await user.click(within(ap).getByRole('button', { name: 'Apply' }))
  expect(posts).toContainEqual([
    '/api/routers/ap2/tools/stations/apply',
    { kind: 'neighbours', ifname: 'phy0-ap0', mac: null, target: null, neighbours: [OTHER.bssid], digest: 'd-neighbours' },
  ])
  await user.click(within(ap).getByRole('button', { name: 'Clear' }))
  await within(ap).findByText(RUNTIME)
  await user.click(within(ap).getByRole('button', { name: 'Apply' }))
  expect(posts).toContainEqual([
    '/api/routers/ap2/tools/stations/apply',
    { kind: 'neighbours', ifname: 'phy0-ap0', mac: null, target: null, neighbours: [], digest: 'd-neighbours' },
  ])
})

test('hostapd saying no is an alert', async () => {
  result = { ok: false, detail: NOT_SUPPORTED, events: [], beacons: [], status_code: null }
  const user = show()
  const ap = await screen.findByRole('region', { name: 'OwgTest (phy0-ap0, channel 11)' })
  await user.click(within(ap).getByRole('button', { name: `BSS transition request to ${MAC}` }))
  await within(ap).findByText(/ubus call hostapd.phy0-ap0 transition/)
  await user.click(within(ap).getByRole('button', { name: 'Apply' }))
  expect(await within(ap).findByText(NOT_SUPPORTED)).toHaveAttribute('role', 'alert')
})

test('an AP whose hostapd lacks a method hides that action and says why', async () => {
  view = stationsView(['rrm_nr_get_own', 'rrm_nr_list', 'rrm_nr_set'])
  show()
  const ap = await screen.findByRole('region', { name: 'OwgTest (phy0-ap0, channel 11)' })
  expect(within(ap).queryByRole('button', { name: /BSS transition request/ })).toBeNull()
  expect(within(ap).queryByRole('button', { name: /Beacon report request/ })).toBeNull()
  expect(within(ap).getByText("This router's hostapd has no bss_transition_request: it needs a full wpad build.")).toBeInTheDocument()
  expect(within(ap).getByText("This router's hostapd has no rrm_beacon_req: it needs a full wpad build.")).toBeInTheDocument()
})
