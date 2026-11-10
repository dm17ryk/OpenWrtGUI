import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { AP2_RC_LOCAL, AP2_SERVICE_PLAN, AP2_SERVICE_RESULT, AP2_SERVICES } from '../../testing/system'
import { ServicesTab } from './ServicesTab'

const calls: Array<{ path: string; body: unknown }> = []

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path === '/api/routers/ap2/system/services') return AP2_SERVICES
      if (path === '/api/routers/ap2/system/rc-local') return { text: AP2_RC_LOCAL }
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body?: unknown) => {
      calls.push({ path, body })
      if (path === '/api/routers/ap2/system/service/preview') return AP2_SERVICE_PLAN
      if (path === '/api/routers/ap2/system/service/apply') return AP2_SERVICE_RESULT
      if (path === '/api/routers/ap2/system/rc-local/preview') {
        throw new actual.ApiError(422, 'The last line of rc.local is exit 0: the boot waits for it', null)
      }
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
      <ServicesTab routerId="ap2" routerName="AP2 · office" />
    </QueryClientProvider>,
  )
}

const row = async (name: string) => within(await screen.findByRole('table', { name: 'Services' })).getByRole('row', { name: new RegExp(`^${name}\\b`) })

test("the app's own path offers Restart only, with the reason", async () => {
  renderTab()
  const dropbear = await row('dropbear')
  expect(within(dropbear).getAllByRole('button').map((b) => b.textContent)).toEqual(['Restart'])
  expect(dropbear).toHaveTextContent('This app reaches the router over SSH (dropbear)')
  const ntp = await row('sysntpd')
  expect(within(ntp).getAllByRole('button').map((b) => b.textContent)).toEqual(['Stop', 'Restart', 'Disable'])
})

test('an action previews and applies with its digest', async () => {
  const user = userEvent.setup()
  renderTab()
  await user.click(within(await row('sysntpd')).getByRole('button', { name: 'Restart' }))
  const preview = await screen.findByRole('region', { name: 'Command preview' })
  expect(preview).toHaveTextContent('/etc/init.d/sysntpd restart')
  expect(calls.at(-1)).toEqual({ path: '/api/routers/ap2/system/service/preview', body: { name: 'sysntpd', action: 'restart' } })
  await user.click(screen.getByRole('button', { name: 'Apply' }))
  expect(calls.at(-1)).toEqual({ path: '/api/routers/ap2/system/service/apply', body: { name: 'sysntpd', action: 'restart', digest: AP2_SERVICE_PLAN.digest } })
  expect(await screen.findByRole('status', { name: 'Apply result' })).toHaveTextContent('Applied and checked')
})

test('rc.local without exit 0 last shows the refusal', async () => {
  const user = userEvent.setup()
  renderTab()
  const editor = await screen.findByRole('textbox', { name: 'rc.local' })
  expect(editor).toHaveValue(AP2_RC_LOCAL)
  await user.clear(editor)
  await user.type(editor, 'logger boot')
  expect(await screen.findByText('The last line of rc.local is exit 0: the boot waits for it')).toBeInTheDocument()
  expect(calls.at(-1)).toEqual({ path: '/api/routers/ap2/system/rc-local/preview', body: { text: 'logger boot' } })
  expect(ApiError).toBeDefined()
})
