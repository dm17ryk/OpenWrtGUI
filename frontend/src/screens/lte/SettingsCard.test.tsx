import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { AP2_LTE, AP2_LTE_OPTIONS, LTE_APN_PLAN, LTE_PASSWORD_PLAN, LTE_SETTINGS_RESULT } from '../../testing/lte'
import { AP2_NET } from '../../testing/net'
import { SettingsCard } from './SettingsCard'

const calls: Array<{ path: string; body: unknown }> = []

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path === '/api/routers/ap2/lte/settings/options') return AP2_LTE_OPTIONS
      if (path === '/api/routers/ap2/network') return AP2_NET
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body?: unknown) => {
      calls.push({ path, body })
      if (path === '/api/routers/ap2/lte/settings/preview') return (body as { password?: string }).password ? LTE_PASSWORD_PLAN : LTE_APN_PLAN
      if (path === '/api/routers/ap2/lte/settings/apply') return LTE_SETTINGS_RESULT
      throw new Error(`unexpected ${path}`)
    }),
  }
})

const onApplied = vi.fn()

beforeEach(() => {
  calls.length = 0
  onApplied.mockClear()
})

function renderSettings() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <SettingsCard routerId="ap2" routerName="AP2 · office" autoconnectNote={AP2_LTE.autoconnect_note} onApplied={onApplied} />
    </QueryClientProvider>,
  )
}

test('the form starts from the router config; an APN edit previews and applies with rollback', async () => {
  const user = userEvent.setup()
  renderSettings()
  const apn = await screen.findByRole('textbox', { name: 'APN' })
  expect(apn).toHaveValue('uinternet')
  expect(screen.getByRole('combobox', { name: 'Authentication' })).toHaveValue('none')
  expect(screen.getByRole('combobox', { name: 'PDP type' })).toHaveValue('ipv4')
  expect(screen.getByRole('textbox', { name: 'MTU' })).toHaveValue('1420')
  expect(screen.getByRole('checkbox', { name: 'Bring up at boot' })).toBeChecked()
  expect(screen.queryByRole('region', { name: 'Command preview' })).not.toBeInTheDocument()
  await user.clear(apn)
  await user.type(apn, 'internet')
  const preview = await screen.findByRole('region', { name: 'Command preview' })
  expect(preview).toHaveTextContent("set network.lte.apn='internet'")
  expect(calls.at(-1)).toEqual({ path: '/api/routers/ap2/lte/settings/preview', body: { apn: 'internet' } })
  await user.click(screen.getByRole('button', { name: 'Apply with rollback' }))
  expect(calls.at(-1)).toEqual({ path: '/api/routers/ap2/lte/settings/apply', body: { apn: 'internet', digest: LTE_APN_PLAN.digest } })
  expect(await screen.findByRole('status', { name: 'Apply result' })).toHaveTextContent('Applied and confirmed')
  expect(onApplied).toHaveBeenCalled()
})

test('the password field starts empty and its preview hides the value', async () => {
  const user = userEvent.setup()
  renderSettings()
  const password = await screen.findByLabelText('Password')
  expect(password).toHaveValue('')
  expect(password).toHaveAttribute('type', 'password')
  expect(screen.getByLabelText('SIM PIN')).toHaveValue('')
  await user.type(password, 's3cret-pw')
  const preview = await screen.findByRole('region', { name: 'Command preview' })
  expect(preview).toHaveTextContent("set network.lte.password='<hidden>'")
  expect(preview).not.toHaveTextContent('s3cret-pw')
  expect(calls.at(-1)?.body).toEqual({ password: 's3cret-pw' })
})

test('the autoconnect and lte_4 DHCP notes are always visible', async () => {
  renderSettings()
  expect(await screen.findByText(AP2_LTE.autoconnect_note)).toBeInTheDocument()
  expect(screen.getByText(/lte_4 must stay DHCP/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Help: Settings' })).toBeInTheDocument()
})

test('All options show the fields above and the locked options read-only', async () => {
  const user = userEvent.setup()
  renderSettings()
  await user.click(await screen.findByRole('button', { name: 'Show all options' }))
  const table = screen.getByRole('table')
  expect(within(table).queryByRole('textbox', { name: 'apn' })).not.toBeInTheDocument()
  expect(within(table).queryByRole('combobox', { name: 'autoconnect' })).not.toBeInTheDocument()
  expect(within(table).queryByRole('textbox', { name: 'metric' })).not.toBeInTheDocument()
  expect(table).toHaveTextContent('set above: Settings')
  expect(table).toHaveTextContent('set above: LTE screen')
})
