import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { AP2, SUMMARY } from '../testing/fixtures'
import { LUCI_PAGES } from '../testing/luci'
import { RouterOverview } from './RouterOverview'

const calls: Array<{ path: string; method: string }> = []

vi.mock('../api/client', async (orig) => {
  const actual = await orig<typeof import('../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn((path: string, init: RequestInit = {}) => {
      calls.push({ path, method: init.method ?? 'GET' })
      if (path === '/api/routers/ap2' && init.method === 'DELETE') return Promise.resolve({ ok: true })
      if (path === '/api/routers/ap2') return Promise.resolve({ ...AP2, summary: SUMMARY })
      if (path === '/api/routers/ap2/luci/pages') return Promise.resolve(LUCI_PAGES)
      return Promise.reject(new Error(`unexpected ${path}`))
    }),
  }
})

beforeEach(() => {
  calls.length = 0
})

afterEach(() => {
  vi.restoreAllMocks()
})

function renderOverview() {
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/routers/ap2']}>
        <Routes>
          <Route path="/" element={<p>the dashboard</p>} />
          <Route path="/routers/:id" element={<RouterOverview />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return user
}

test('Remove from the app asks, then removes and goes to the dashboard', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
  const user = renderOverview()
  await user.click(await screen.findByRole('button', { name: 'Remove from the app' }))
  expect(confirm).toHaveBeenCalledWith('Remove AP2 · office from OpenWrtGUI? The router itself is not changed.')
  expect(await screen.findByText('the dashboard')).toBeInTheDocument()
  expect(calls).toContainEqual({ path: '/api/routers/ap2', method: 'DELETE' })
})

test('saying no keeps the router', async () => {
  vi.spyOn(window, 'confirm').mockReturnValue(false)
  const user = renderOverview()
  await user.click(await screen.findByRole('button', { name: 'Remove from the app' }))
  expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('AP2 · office')
})
