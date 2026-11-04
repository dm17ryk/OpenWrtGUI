import { QueryClient } from '@tanstack/react-query'
import { expect, test } from 'vitest'
import { applyLive } from './live'
import type { RouterItem } from './types'

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
