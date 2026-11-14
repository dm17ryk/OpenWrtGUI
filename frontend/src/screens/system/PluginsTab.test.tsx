import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { AP4_PLUGIN_OFF_PLAN, AP4_PLUGINS } from '../../testing/later'
import { PluginsTab } from './PluginsTab'

const calls: Array<{ path: string; body: unknown }> = []
const base = '/api/routers/ap4/system/plugins'

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path === base) return AP4_PLUGINS
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body?: unknown) => {
      calls.push({ path, body })
      if (path === `${base}/preview`) return AP4_PLUGIN_OFF_PLAN
      throw new Error(`unexpected ${path}`)
    }),
  }
})

beforeEach(() => {
  calls.length = 0
})

function renderTab() {
  render(
    <MemoryRouter>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <PluginsTab routerId="ap4" routerName="AP4 · later image" />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

test('the switches, the plugins and their options', async () => {
  renderTab()
  expect(await screen.findByText('Content Security Policy')).toBeInTheDocument()
  expect(screen.getByText('mode=strict')).toBeInTheDocument()
  expect(screen.getByLabelText('Plugins on')).toBeChecked()
  expect(screen.getByText(/Missing plugin/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Remove' })).toBeEnabled()
  expect(screen.getByRole('link', { name: 'Configure in LuCI' })).toHaveAttribute('href', '/routers/ap4/luci?page=admin%2Fsystem%2Fplugins')
  expect(screen.getByRole('button', { name: 'Help: Plugins' })).toBeInTheDocument()
})

test('a plugin switched off is previewed', async () => {
  const user = userEvent.setup()
  renderTab()
  await user.click(await screen.findByLabelText('Content-Security-Policy on'))
  const preview = await screen.findByRole('region', { name: 'Command preview' })
  expect(preview).toHaveTextContent('uci -q delete luci_plugins.c0ffee2cf63e160c091224d95d69cdff.enabled')
  expect(calls.at(-1)).toEqual({
    path: `${base}/preview`,
    body: { groups: {}, plugins: { c0ffee2cf63e160c091224d95d69cdff: false }, remove: [] },
  })
})
