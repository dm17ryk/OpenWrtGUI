import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { afterEach, expect, test, vi } from 'vitest'
import { parseFrame } from './frames'
import { applyLive, useLive } from './live'
import type { RouterItem } from './types'

afterEach(() => {
  vi.unstubAllGlobals()
})

test('parseFrame gives null for a frame that is not JSON', () => {
  expect(parseFrame('{not json')).toBeNull()
  expect(parseFrame('{"type":"guard"}')).toEqual({ type: 'guard' })
})

test('a /ws/live frame that is not JSON is dropped; the next one still lands (#77 minor 11)', () => {
  const sockets: Array<{ onmessage: ((ev: { data: string }) => void) | null }> = []
  vi.stubGlobal(
    'WebSocket',
    class {
      onmessage: ((ev: { data: string }) => void) | null = null
      onclose: (() => void) | null = null
      constructor() {
        sockets.push(this)
      }
      close(): void {}
    },
  )
  const client = new QueryClient()
  const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children)
  renderHook(() => useLive(), { wrapper })
  expect(() => act(() => sockets[0].onmessage?.({ data: '{not json' }))).not.toThrow()
  const state = { live: false, reasons: [], checked_at: 'y' }
  act(() => sockets[0].onmessage?.({ data: JSON.stringify({ type: 'guard', state }) }))
  expect(client.getQueryData(['guard'])).toEqual(state)
})

const item = (id: string): RouterItem => ({
  record: { id, name: id, host: '192.168.1.2', port: 22, username: 'root', auth: 'key', port_labels: {}, added_at: '2026-11-03T09:00:00' },
  health: { online: true, since: '2026-11-03T09:00:00', error: null },
  status: null,
  summary: null,
})

test('router-offline marks only that router offline', () => {
  const client = new QueryClient()
  client.setQueryData(['routers'], [item('ap1'), item('ap2')])
  applyLive(client, { type: 'router-offline', router: 'ap2', since: '2026-11-03T12:00:00', error: 'timed out' })
  const items = client.getQueryData<RouterItem[]>(['routers'])
  expect(items?.map((i) => i.health.online)).toEqual([true, false])
  expect(items?.[1].health.error).toBe('timed out')
})

test('guard message lands in the guard query', () => {
  const client = new QueryClient()
  applyLive(client, { type: 'guard', state: { live: true, reasons: [], checked_at: 'x' } })
  expect(client.getQueryData(['guard'])).toEqual({ live: true, reasons: [], checked_at: 'x' })
})
