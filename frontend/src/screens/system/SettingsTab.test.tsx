import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { AP2_HOSTNAME_PLAN, AP2_HOSTNAME_RESULT, AP2_SETTINGS, AP2_ZONES } from '../../testing/system'
import { SettingsTab } from './SettingsTab'

const calls: Array<{ path: string; body: unknown }> = []

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path === '/api/routers/ap2/system/settings') return AP2_SETTINGS
      if (path === '/api/routers/ap2/system/timezones') return AP2_ZONES
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body?: unknown) => {
      calls.push({ path, body })
      if (path === '/api/routers/ap2/system/settings/preview') return AP2_HOSTNAME_PLAN
      if (path === '/api/routers/ap2/system/settings/apply') return AP2_HOSTNAME_RESULT
      throw new Error(`unexpected ${path}`)
    }),
  }
})

beforeEach(() => {
  calls.length = 0
})

function renderTab() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <SettingsTab routerId="ap2" routerName="AP2 · office" />
    </QueryClientProvider>,
  )
}

test('the form starts from the router; a host name edit previews and applies with its digest', async () => {
  const user = userEvent.setup()
  renderTab()
  const host = await screen.findByRole('textbox', { name: 'Host name' })
  expect(host).toHaveValue('OpenWrt')
  expect(screen.getByRole('combobox', { name: 'Time zone' })).toHaveValue('UTC')
  expect(screen.getByRole('textbox', { name: 'NTP servers' })).toHaveValue(AP2_SETTINGS.ntp_servers.join('\n'))
  expect(screen.queryByRole('region', { name: 'Command preview' })).not.toBeInTheDocument()
  await user.clear(host)
  await user.type(host, 'bench-ap2')
  const preview = await screen.findByRole('region', { name: 'Command preview' })
  expect(preview).toHaveTextContent("uci set system.cfg01e48a.hostname='bench-ap2'")
  expect(calls.at(-1)).toEqual({ path: '/api/routers/ap2/system/settings/preview', body: { hostname: 'bench-ap2' } })
  await user.click(screen.getByRole('button', { name: 'Apply' }))
  expect(calls.at(-1)).toEqual({ path: '/api/routers/ap2/system/settings/apply', body: { hostname: 'bench-ap2', digest: AP2_HOSTNAME_PLAN.digest } })
  expect(await screen.findByRole('status', { name: 'Apply result' })).toHaveTextContent('Applied and checked')
  expect(screen.getByRole('button', { name: 'Help: System and time' })).toBeInTheDocument()
})

test('the time zone list from the router is searchable and starts with UTC', async () => {
  const user = userEvent.setup()
  renderTab()
  const zone = await screen.findByRole('combobox', { name: 'Time zone' })
  expect(within(zone).getAllByRole('option')[0]).toHaveTextContent('UTC')
  await user.type(screen.getByRole('searchbox', { name: 'Find a time zone' }), 'jeru')
  expect(within(zone).getAllByRole('option').map((o) => o.textContent)).toEqual(['UTC', 'Asia/Jerusalem'])
  await user.selectOptions(zone, 'Asia/Jerusalem')
  await screen.findByRole('region', { name: 'Command preview' })
  expect(calls.at(-1)).toEqual({ path: '/api/routers/ap2/system/settings/preview', body: { zonename: 'Asia/Jerusalem' } })
})
