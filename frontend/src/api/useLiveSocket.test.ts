import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { reconnectText, useLiveSocket } from './useLiveSocket'

class FakeSocket {
  static all: FakeSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: ((ev: { code: number; reason: string }) => void) | null = null
  readonly url: string
  constructor(url: string) {
    this.url = url
    FakeSocket.all.push(this)
  }
  static last(): FakeSocket {
    return FakeSocket.all[FakeSocket.all.length - 1]
  }
  static count(): number {
    return FakeSocket.all.length
  }
  send(): void {}
  close(): void {}
  fireClose(code: number, reason = ''): void {
    act(() => this.onclose?.({ code, reason }))
  }
  fireMessage(msg: unknown): void {
    act(() => this.onmessage?.({ data: JSON.stringify(msg) }))
  }
}

beforeEach(() => {
  FakeSocket.all = []
  vi.useFakeTimers()
  vi.stubGlobal('WebSocket', FakeSocket)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const noop = (): void => {}

test('an unexpected close reconnects after 1 s, then 2 s', () => {
  const { result } = renderHook(() => useLiveSocket('/ws/lte/ap1', undefined, noop))
  FakeSocket.last().fireClose(1006)
  expect(result.current.phase).toBe('reconnecting')
  expect(reconnectText(result.current)).toBe('Lost the connection to OpenWrtGUI; reconnecting (attempt 1)')
  act(() => void vi.advanceTimersByTime(999))
  expect(FakeSocket.count()).toBe(1)
  act(() => void vi.advanceTimersByTime(1))
  expect(FakeSocket.count()).toBe(2)
  FakeSocket.last().fireClose(1006)
  act(() => void vi.advanceTimersByTime(1999))
  expect(FakeSocket.count()).toBe(2)
  act(() => void vi.advanceTimersByTime(1))
  expect(FakeSocket.count()).toBe(3)
})

test('the app closing with 4404 ends it with its reason', () => {
  const { result } = renderHook(() => useLiveSocket('/ws/lte/ap9', undefined, noop))
  FakeSocket.last().fireClose(4404, 'Unknown router ap9')
  act(() => void vi.advanceTimersByTime(60_000))
  expect(FakeSocket.count()).toBe(1)
  expect([result.current.phase, result.current.attempt, result.current.reason]).toEqual(['ended', 0, 'Unknown router ap9'])
  expect(reconnectText(result.current)).toBe('Unknown router ap9')
})

test('leaving the screen during a retry opens nothing', () => {
  const { unmount } = renderHook(() => useLiveSocket('/ws/lte/ap1', undefined, noop))
  FakeSocket.last().fireClose(1006)
  unmount()
  act(() => void vi.advanceTimersByTime(60_000))
  expect(FakeSocket.count()).toBe(1)
})

test('a message after a reconnect resets the attempt count', () => {
  const seen: unknown[] = []
  const { result } = renderHook(() => useLiveSocket<{ n: number }>('/ws/system/ap1', undefined, (msg) => seen.push(msg)))
  FakeSocket.last().fireClose(1006)
  act(() => void vi.advanceTimersByTime(1000))
  FakeSocket.last().fireMessage({ n: 1 })
  expect(seen).toEqual([{ n: 1 }])
  expect([result.current.phase, result.current.attempt]).toEqual(['open', 0])
  expect(reconnectText(result.current)).toBeNull()
  FakeSocket.last().fireClose(1006)
  act(() => void vi.advanceTimersByTime(1000))
  expect(FakeSocket.count()).toBe(3) // back to the 1 s step, not 2 s
})

test('no path opens nothing', () => {
  renderHook(() => useLiveSocket(null, undefined, noop))
  expect(FakeSocket.count()).toBe(0)
})
