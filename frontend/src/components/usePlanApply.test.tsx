import { act, renderHook, waitFor } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { usePlanApply } from './usePlanApply'

const PLAN = { lines: ['do it'], warnings: [], digest: 'd1', rollback: false, router_id: 'ap2', screen: 'x', target_host: null }

vi.mock('../api/client', async (orig) => {
  const actual = await orig<typeof import('../api/client')>()
  return {
    ...actual,
    postJson: vi.fn(async (path: string) => {
      if (path.endsWith('/preview')) return PLAN
      if (path.endsWith('/apply')) return { ok: true, applied: false, lines: [] }
      throw new Error(`unexpected ${path}`)
    }),
  }
})

type Done = { ok: boolean; applied: boolean; lines: string[] }

test('isDone decides whether onApplied runs, instead of the applied field', async () => {
  const onApplied = vi.fn()
  const { result } = renderHook(() => usePlanApply<Done>('/x', { a: 1 }, onApplied, (r) => r.ok))
  await waitFor(() => expect(result.current.plan?.digest).toBe('d1'))
  await act(async () => {
    await result.current.apply()
  })
  expect(result.current.result).toEqual({ ok: true, applied: false, lines: [] })
  expect(onApplied).toHaveBeenCalledTimes(1)
})

test('without isDone the applied field still decides', async () => {
  const onApplied = vi.fn()
  const { result } = renderHook(() => usePlanApply<Done>('/x', { a: 1 }, onApplied))
  await waitFor(() => expect(result.current.plan?.digest).toBe('d1'))
  await act(async () => {
    await result.current.apply()
  })
  expect(result.current.result).not.toBeNull()
  expect(onApplied).not.toHaveBeenCalled()
})
