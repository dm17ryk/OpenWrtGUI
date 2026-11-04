import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { expect, test, vi } from 'vitest'
import type { AuditEntry } from '../api/types'
import { ROUTERS } from '../testing/fixtures'
import { AuditLog } from './AuditLog'

const fetched: string[] = []
const ENTRY: AuditEntry = {
  ts: '2026-11-03T14:29:00+02:00',
  router: 'ap2',
  screen: 'Terminal',
  command: 'uname -a',
  exit_status: 0,
  verify: null,
  source: 'terminal',
}

vi.mock('../api/client', async (orig) => {
  const actual = await orig<typeof import('../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      fetched.push(path)
      if (path.startsWith('/api/routers')) return ROUTERS
      return [ENTRY]
    }),
  }
})

test('audit filter by router sends query', async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AuditLog />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect(await screen.findByText('uname -a')).toBeInTheDocument()
  await userEvent.setup().selectOptions(await screen.findByLabelText('Router'), 'ap2')
  await screen.findByText('uname -a')
  expect(fetched.some((p) => p.startsWith('/api/audit?') && p.includes('router=ap2'))).toBe(true)
})
