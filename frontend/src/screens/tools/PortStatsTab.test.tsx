import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { PortStats } from '../../api/types'
import { PortStatsTab } from './PortStatsTab'

let reads: Array<PortStats | ApiError> = []

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path !== '/api/routers/ap1/ports/stats') throw new Error(`unexpected ${path}`)
      const next = reads.length > 1 ? reads.shift() : reads[0]
      if (next instanceof Error) throw next
      return next
    }),
  }
})

// 12:03:04 local time on 2026-11-19, as Unix seconds
const T0 = new Date(2026, 10, 19, 12, 3, 4).getTime() / 1000

function read(at: number, rxBytes: number, txBytes: number, rxErrors = 0): PortStats {
  return {
    switch: 'switch0',
    read_at: at,
    note: null,
    ports: [
      {
        num: 3,
        label: 'LAN1',
        link: true,
        speed_mbps: 100,
        totals: { rx_packets: 100, rx_bytes: rxBytes, rx_errors: rxErrors, tx_packets: 50, tx_bytes: txBytes, tx_errors: 0 },
        raw: { RxGPC: 100, RxGOC: rxBytes, RxEPC1: rxErrors, TxGPC: 50, TxGOC: txBytes, TxEPC: 0 },
        bits: { RxGPC: 16, RxGOC: 32, RxEPC1: 16, TxGPC: 16, TxGOC: 32, TxEPC: 16 },
        columns: {
          RxGPC: 'rx_packets',
          RxGOC: 'rx_bytes',
          RxEPC1: 'rx_errors',
          TxGPC: 'tx_packets',
          TxGOC: 'tx_bytes',
          TxEPC: 'tx_errors',
        },
      },
    ],
  }
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  reads = []
})

afterEach(() => {
  vi.useRealTimers()
})

function show(client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return render(
    <QueryClientProvider client={client}>
      <PortStatsTab routerId="ap1" />
    </QueryClientProvider>,
  )
}

test('the table wears the app table style and scrolls on its own', async () => {
  reads = [read(T0, 1_000_000, 500)]
  show()
  const table = await screen.findByRole('table')
  expect(table).toHaveClass('tbl')
  expect(table.parentElement).toHaveClass('scroll-x')
})

test('coming back to the tab starts counting from a fresh read, not a cached one', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  reads = [read(T0, 1_000_000, 500)]
  const first = show(client)
  await screen.findByText('Since 12:03:04')
  first.unmount()
  reads = [read(T0 + 60, 9_000_000, 900)]
  show(client)
  expect(await screen.findByText('Since 12:04:04')).toBeInTheDocument()
  expect(screen.queryByText('Since 12:03:04')).toBeNull()
})

test('the columns, counted since the tab opened', async () => {
  reads = [read(T0, 1_000_000, 500)]
  show()
  const table = await screen.findByRole('table')
  expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
    'Port',
    'Link',
    'Rx packets',
    'Rx bytes',
    'Rx errors',
    'Tx packets',
    'Tx bytes',
    'Tx errors',
    'Rx rate',
    'Tx rate',
  ])
  expect(screen.getByText('Since 12:03:04')).toBeInTheDocument()
  const row = within(table).getByRole('row', { name: /LAN1/ })
  expect(within(row).getAllByRole('cell').map((c) => c.textContent)).toEqual([
    'LAN1',
    '100 Mbit/s',
    '0',
    '0 B',
    '0',
    '0',
    '0 B',
    '0',
    '—',
    '—',
  ])
})

test('a second read fills the rates and the counts since the start', async () => {
  reads = [read(T0, 1_000_000, 500), read(T0 + 5, 7_000_000, 1_500, 2)]
  show()
  await screen.findByText('Since 12:03:04')
  await act(() => vi.advanceTimersByTimeAsync(5000))
  const row = await screen.findByRole('row', { name: /9\.6 Mbit\/s/ })
  const cells = within(row).getAllByRole('cell').map((c) => c.textContent)
  expect(cells.slice(3, 5)).toEqual(['6.0 MB', '2'])
  expect(within(row).getAllByRole('cell')[4]).toHaveClass('warn') // an error since the start is marked
  expect(cells.slice(8)).toEqual(['9.6 Mbit/s', '1.6 kbit/s'])
})

test('Start over counts again from the last read', async () => {
  reads = [read(T0, 1_000_000, 500), read(T0 + 5, 7_000_000, 1_500)]
  show()
  await screen.findByText('Since 12:03:04')
  await act(() => vi.advanceTimersByTimeAsync(5000))
  await screen.findByRole('row', { name: /9\.6 Mbit\/s/ })
  act(() => screen.getByRole('button', { name: 'Start over' }).click())
  expect(screen.getByText('Since 12:03:09')).toBeInTheDocument()
  const row = screen.getByRole('row', { name: /LAN1/ })
  expect(within(row).getAllByRole('cell')[3]).toHaveTextContent('0 B')
})

test('All counters lists every counter the switch printed', async () => {
  reads = [read(T0, 1_000_000, 500)]
  show()
  await screen.findByRole('table')
  const all = screen.getByText('All counters')
  expect(all.closest('details')).toHaveTextContent('RxGOC1000000')
})

test('a note instead of the table', async () => {
  reads = [{ switch: null, read_at: T0, ports: [], note: 'This router has no swconfig switch, so it has no port counters here.' }]
  show()
  expect(await screen.findByText('This router has no swconfig switch, so it has no port counters here.')).toBeInTheDocument()
  expect(screen.queryByRole('table')).toBeNull()
})

test('a failed read keeps the counts and blanks the rates', async () => {
  reads = [read(T0, 1_000_000, 500), read(T0 + 5, 7_000_000, 1_500), new ApiError(503, 'ap1 did not answer', null)]
  show()
  await screen.findByText('Since 12:03:04')
  await act(() => vi.advanceTimersByTimeAsync(5000))
  await screen.findByRole('row', { name: /9\.6 Mbit\/s/ })
  await act(() => vi.advanceTimersByTimeAsync(5000))
  expect(await screen.findByText('ap1 did not answer')).toBeInTheDocument()
  const row = screen.getByRole('row', { name: /LAN1/ })
  const cells = within(row).getAllByRole('cell').map((c) => c.textContent)
  expect(cells[3]).toBe('6.0 MB')
  expect(cells.slice(8)).toEqual(['—', '—'])
})
