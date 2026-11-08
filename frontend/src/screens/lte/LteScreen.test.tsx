import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { LteMessage, LteState } from '../../api/types'
import { AP2 } from '../../testing/fixtures'
import { AP2_LTE, AP2_LTE_OPTIONS, NO_LTE } from '../../testing/lte'
import { LteScreen } from './LteScreen'

vi.mock('uplot', () => ({
  default: class {
    setData(): void {}
    setSize(): void {}
    destroy(): void {}
  },
}))

let state: LteState = AP2_LTE

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path === '/api/routers/ap2') return AP2
      if (path === '/api/routers/ap2/lte') return state
      if (path === '/api/routers/ap2/lte/settings/options') return AP2_LTE_OPTIONS
      if (path === '/api/routers/ap2/luci/pages') return []
      throw new Error(`unexpected ${path}`)
    }),
  }
})

class FakeSocket {
  static last: FakeSocket | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  readonly url: string
  constructor(url: string) {
    this.url = url
    FakeSocket.last = this
  }
  send(): void {}
  close(): void {}
  emit(msg: LteMessage): void {
    act(() => this.onmessage?.({ data: JSON.stringify(msg) }))
  }
}

beforeEach(() => {
  state = AP2_LTE
  vi.stubGlobal('WebSocket', FakeSocket)
})
afterEach(() => vi.unstubAllGlobals())

function renderLte() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/routers/ap2/lte']}>
        <Routes>
          <Route path="/routers/:id/lte" element={<LteScreen />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('status shows registration, radio, operator and the labelled signal', async () => {
  renderLte()
  expect(await screen.findByRole('heading', { name: 'LTE', level: 1 })).toBeInTheDocument()
  const status = await screen.findByRole('region', { name: 'Status' })
  expect(status).toHaveTextContent('registered')
  expect(status).toHaveTextContent('LTE')
  expect(status).toHaveTextContent('Partner')
  expect(status).toHaveTextContent('425 / 01')
  expect(status).toHaveTextContent('10.64.12.7')
  const rsrp = screen.getByRole('region', { name: 'RSRP' })
  expect(rsrp).toHaveTextContent('−95 dBm')
  expect(within(rsrp).getByText('fair')).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'SNR' })).toHaveTextContent('8.2 dB')
  for (const name of ['LTE modem', 'Status', 'Signal quality', 'Live signal']) {
    expect(screen.getByRole('button', { name: `Help: ${name}` })).toBeInTheDocument()
  }
})

test('an operator name from QMI is marked as possibly garbled', async () => {
  state = { ...AP2_LTE, operator_source: 'qmi' }
  renderLte()
  expect(await screen.findByRole('region', { name: 'Status' })).toHaveTextContent('Partner (from QMI, may be garbled)')
})

test('live samples update the values; an idle message shows its reason', async () => {
  renderLte()
  await screen.findByRole('region', { name: 'Status' })
  expect(FakeSocket.last?.url).toContain('/ws/lte/ap2')
  FakeSocket.last?.emit({ type: 'lte-idle', reason: 'No answer from the modem' })
  expect(screen.getByRole('status')).toHaveTextContent('No answer from the modem')
  FakeSocket.last?.emit({
    type: 'lte',
    sample: { t: 1_794_139_200, rssi: -70, rsrp: -102, rsrq: -12, snr: 3.5, registration: 'registered', radio: 'lte' },
  })
  const rsrp = screen.getByRole('region', { name: 'RSRP' })
  expect(rsrp).toHaveTextContent('−102 dBm')
  expect(within(rsrp).getByText('poor')).toBeInTheDocument()
  expect(screen.queryByText('No answer from the modem')).not.toBeInTheDocument()
  for (const chart of ['RSSI', 'RSRP', 'RSRQ', 'SNR']) {
    expect(screen.getByRole('figure', { name: chart })).toBeInTheDocument()
  }
})

test('parts of the modem that did not answer are named', async () => {
  state = { ...AP2_LTE, missing: ['signal', 'AT'] }
  renderLte()
  expect(await screen.findByText('No answer from the modem for: signal, AT')).toBeInTheDocument()
})

test('a router without LTE shows the note only', async () => {
  state = NO_LTE
  renderLte()
  expect(await screen.findByText(NO_LTE.note ?? '')).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'Status' })).not.toBeInTheDocument()
  expect(screen.queryByRole('figure', { name: 'RSRP' })).not.toBeInTheDocument()
})
