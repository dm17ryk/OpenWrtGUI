import { expect, test } from 'vitest'
import { PANEL_SAMPLE as STA, rfSample as sample } from '../../testing/rf'
import { MAX_POINTS, pushSample, toUplot, windowed, type Buffers } from './series'

test('pushSample adds a point per station and leaves the old buffers alone', () => {
  const empty: Buffers = {}
  const one = pushSample(empty, sample(0))
  expect(empty).toEqual({})
  expect(one[STA.mac].signal.map((p) => p.v)).toEqual([-52])
  expect(one[STA.mac].tx.map((p) => p.v)).toEqual([65])
  expect(one[STA.mac].rx.map((p) => p.v)).toEqual([54])
})

test('a station missing from a sample gets a gap', () => {
  const b = pushSample(pushSample({}, sample(0)), sample(1, []))
  expect(b[STA.mac].signal.map((p) => p.v)).toEqual([-52, null])
})

test('buffers are capped', () => {
  let b: Buffers = {}
  for (let i = 0; i < MAX_POINTS + 5; i++) b = pushSample(b, sample(i % 60))
  expect(b[STA.mac].signal).toHaveLength(MAX_POINTS)
})

test('windowed keeps the last window and toUplot gives seconds', () => {
  const points = [
    { t: 1_000_000, v: -50 },
    { t: 1_200_000, v: -51 },
    { t: 1_290_000, v: -52 },
  ]
  expect(windowed(points, 1_300_000, 100)).toEqual(points.slice(1))
  expect(windowed(points, 1_300_000, 60)).toEqual(points.slice(2))
  expect(toUplot(points.slice(1))).toEqual([
    [1200, 1290],
    [-51, -52],
  ])
})
