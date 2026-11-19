import { expect, test } from 'vitest'
import type { PortStats } from '../../api/types'
import { accumulate, counterDelta, emptySince, formatBits, formatBytes, rate } from './portRates'

/** One port, AP2's mt7620 counters: packets and errors 16-bit, octets 32-bit. */
function stats(readAt: number, c: { rxBytes?: number; rxPackets?: number; e1?: number; e2?: number }, speed = 100): PortStats {
  const raw: Record<string, number> = {}
  if (c.rxBytes !== undefined) raw.RxGOC = c.rxBytes
  if (c.rxPackets !== undefined) raw.RxGPC = c.rxPackets
  if (c.e1 !== undefined) raw.RxEPC1 = c.e1
  if (c.e2 !== undefined) raw.RxEPC2 = c.e2
  const columns: Record<string, string> = { RxGOC: 'rx_bytes', RxGPC: 'rx_packets', RxEPC1: 'rx_errors', RxEPC2: 'rx_errors' }
  const bits: Record<string, number> = { RxGOC: 32, RxGPC: 16, RxEPC1: 16, RxEPC2: 16 }
  return {
    switch: 'switch0',
    read_at: readAt,
    note: null,
    ports: [
      {
        num: 3,
        label: 'LAN1',
        link: true,
        speed_mbps: speed,
        totals: { rx_packets: null, rx_bytes: null, rx_errors: null, tx_packets: null, tx_bytes: null, tx_errors: null },
        raw,
        bits: Object.fromEntries(Object.keys(raw).map((k) => [k, bits[k]])),
        columns: Object.fromEntries(Object.keys(raw).map((k) => [k, columns[k]])),
      },
    ],
  }
}

test('a counter that grew, wrapped at its own width, or reset', () => {
  expect(counterDelta(10, 25)).toBe(15)
  expect(counterDelta(4294967000, 500)).toBe(796) // a 32-bit wrap
  expect(counterDelta(900, 100)).toBe('reset')
  expect(counterDelta(65000, 500, 16)).toBe(1036) // a 16-bit wrap
  expect(counterDelta(30000, 100, 16)).toBe('reset') // below half of 2^16 before: a reset, not a wrap
})

test('a rate per second from two reads', () => {
  expect(rate(stats(100, { rxBytes: 1_000_000 }), stats(105, { rxBytes: 7_000_000 }), 3, 'rx_bytes')).toBe(1_200_000)
  expect(rate(stats(100, { rxPackets: 65000 }), stats(105, { rxPackets: 500 }), 3, 'rx_packets')).toBeCloseTo(207.2)
  expect(rate(stats(100, { rxBytes: 900 }), stats(105, { rxBytes: 100 }), 3, 'rx_bytes')).toBe('reset')
  expect(rate(stats(100, {}), stats(105, {}), 3, 'rx_bytes')).toBeNull() // a column the switch does not count
  expect(rate(stats(100, { rxBytes: 1 }), stats(105, { rxBytes: 2 }), 4, 'rx_bytes')).toBeNull() // no such port
  expect(rate(stats(105, { rxBytes: 1 }), stats(105, { rxBytes: 2 }), 3, 'rx_bytes')).toBeNull() // no time passed
})

test('a jump faster than the port can carry is a reset (a reboot above 2^31 is not a wrap)', () => {
  // 3e9 → 1000 over 5 s would be ~2 Gbit/s on a 100 Mbit/s port
  expect(rate(stats(100, { rxBytes: 3_000_000_000 }), stats(105, { rxBytes: 1000 }), 3, 'rx_bytes')).toBe('reset')
  expect(rate(stats(100, { rxBytes: 3_000_000_000 }, 0), stats(105, { rxBytes: 1000 }, 0), 3, 'rx_bytes')).not.toBe('reset') // no speed known: taken as a wrap
})

test('two error counters add up, each wrapping on its own', () => {
  expect(rate(stats(100, { e1: 65530, e2: 10 }), stats(101, { e1: 4, e2: 12 }), 3, 'rx_errors')).toBe(12)
})

test('since counts add every step, through wraps and resets', () => {
  const reads = [
    stats(100, { rxPackets: 60000, rxBytes: 1000 }),
    stats(105, { rxPackets: 64000, rxBytes: 2000 }), // +4000
    stats(110, { rxPackets: 2000, rxBytes: 3000 }), // 16-bit wrap: +3536
    stats(115, { rxPackets: 6000, rxBytes: 4000 }), // +4000
    stats(120, { rxPackets: 50, rxBytes: 60 }), // a reboot: counts since it, +50 / +60
  ]
  let since = emptySince(reads[0])
  expect(since[3]).toEqual({ rx_packets: 0, rx_bytes: 0, rx_errors: null, tx_packets: null, tx_bytes: null, tx_errors: null })
  for (let i = 1; i < reads.length; i += 1) since = accumulate(since, reads[i - 1], reads[i])
  expect(since[3].rx_packets).toBe(4000 + 3536 + 4000 + 50)
  expect(since[3].rx_bytes).toBe(1000 + 1000 + 1000 + 60)
})

test('bytes and bits for people', () => {
  expect(formatBytes(512)).toBe('512 B')
  expect(formatBytes(1_500)).toBe('1.5 kB')
  expect(formatBytes(2_151_276_205)).toBe('2.2 GB')
  expect(formatBits(1_200_000 * 8)).toBe('9.6 Mbit/s')
  expect(formatBits(800)).toBe('800 bit/s')
  expect(formatBits(12_345)).toBe('12.3 kbit/s')
})
