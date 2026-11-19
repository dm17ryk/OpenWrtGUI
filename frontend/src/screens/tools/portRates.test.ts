import { expect, test } from 'vitest'
import type { PortStats } from '../../api/types'
import { counterDelta, formatBits, formatBytes, rate, sinceBaseline } from './portRates'

function stats(readAt: number, rxBytes: number | null, num = 3): PortStats {
  return {
    switch: 'switch0',
    read_at: readAt,
    note: null,
    ports: [
      {
        num,
        label: 'LAN1',
        link: true,
        speed_mbps: 100,
        totals: { rx_packets: 10, rx_bytes: rxBytes, rx_errors: 0, tx_packets: 5, tx_bytes: 900, tx_errors: 0 },
        raw: {},
      },
    ],
  }
}

test('a counter that grew, wrapped or reset', () => {
  expect(counterDelta(10, 25)).toBe(15)
  expect(counterDelta(4294967000, 500)).toBe(796) // a 32-bit wrap
  expect(counterDelta(900, 100)).toBe('reset') // went down from below 2^31: a reboot or a clear
  expect(counterDelta(7, 7)).toBe(0)
})

test('a rate per second from two reads', () => {
  expect(rate(stats(100, 1_000_000), stats(105, 7_000_000), 3, 'rx_bytes')).toBe(1_200_000)
  expect(rate(stats(100, 900), stats(105, 100), 3, 'rx_bytes')).toBe('reset')
  expect(rate(stats(100, null), stats(105, 7), 3, 'rx_bytes')).toBeNull() // a column the switch does not count
  expect(rate(stats(100, 1), stats(105, 2), 4, 'rx_bytes')).toBeNull() // no such port
  expect(rate(stats(105, 1), stats(105, 2), 3, 'rx_bytes')).toBeNull() // no time between the reads
})

test('a value since the baseline', () => {
  expect(sinceBaseline(stats(100, 1000), stats(200, 4000), 3, 'rx_bytes')).toBe(3000)
  expect(sinceBaseline(stats(100, 4000), stats(200, 1000), 3, 'rx_bytes')).toBe('reset')
  expect(sinceBaseline(stats(100, null), stats(200, 1000), 3, 'rx_bytes')).toBeNull()
})

test('bytes and bits for people', () => {
  expect(formatBytes(512)).toBe('512 B')
  expect(formatBytes(1_500)).toBe('1.5 kB')
  expect(formatBytes(2_151_276_205)).toBe('2.2 GB')
  expect(formatBits(1_200_000 * 8)).toBe('9.6 Mbit/s')
  expect(formatBits(800)).toBe('800 bit/s')
  expect(formatBits(12_345)).toBe('12.3 kbit/s')
})
