import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import {
  AP2_ACCESS,
  AP2_ACCESS_OWNED,
  AP2_HTTP_OFF_PLAN,
  AP2_KEY_ADD_PLAN,
  AP2_NEW_KEY,
  AP2_PASSWORD_PLAN,
  AP2_PASSWORD_RESULT,
  AP2_SSH_ADD_PLAN,
} from '../../testing/system'
import { AccessTab } from './AccessTab'

const PASSWORD = 'Bench-only-7'
const calls: Array<{ method: string; path: string; body?: unknown }> = []
let access = AP2_ACCESS
const base = '/api/routers/ap2/system'

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      calls.push({ method: 'GET', path })
      if (path === `${base}/access`) return access
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body?: unknown) => {
      calls.push({ method: 'POST', path, body })
      if (path === `${base}/password/preview`) return AP2_PASSWORD_PLAN
      if (path === `${base}/password/apply`) return AP2_PASSWORD_RESULT
      if (path === `${base}/ssh-keys/preview`) return AP2_KEY_ADD_PLAN
      if (path === `${base}/http/preview`) return AP2_HTTP_OFF_PLAN
      if (path === `${base}/ssh/preview`) return AP2_SSH_ADD_PLAN
      throw new Error(`unexpected ${path}`)
    }),
    putJson: vi.fn(async (path: string, body: unknown) => {
      calls.push({ method: 'PUT', path, body })
      if (path === `${base}/ssh-keys/owner`) return AP2_ACCESS_OWNED
      throw new Error(`unexpected ${path}`)
    }),
  }
})

beforeEach(() => {
  calls.length = 0
  access = AP2_ACCESS
})

function renderTab() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AccessTab routerId="ap2" routerName="AP2 · office" />
    </QueryClientProvider>,
  )
}

const card = (name: string): HTMLElement => screen.getByRole('region', { name })

test('the password reaches only the apply call, and both fields clear after it', async () => {
  const user = userEvent.setup()
  renderTab()
  const pw = await screen.findByLabelText('New password')
  const again = screen.getByLabelText('Confirm the password')
  expect(pw).toHaveAttribute('type', 'password')
  await user.type(pw, PASSWORD)
  expect(screen.queryByRole('region', { name: 'Command preview' })).not.toBeInTheDocument() // not confirmed yet
  await user.type(again, PASSWORD)
  const preview = await within(card('Router password')).findByRole('region', { name: 'Command preview' })
  expect(preview).toHaveTextContent('passwd root')
  await user.click(screen.getByRole('button', { name: 'Set the password' }))
  expect(await within(card('Router password')).findByRole('status', { name: 'Apply result' })).toHaveTextContent('Password changed')
  expect(pw).toHaveValue('')
  expect(again).toHaveValue('')
  const carrying = calls.filter((c) => JSON.stringify(c).includes(PASSWORD))
  expect(carrying).toEqual([{ method: 'POST', path: `${base}/password/apply`, body: { password: PASSWORD, digest: AP2_PASSWORD_PLAN.digest } }])
})

test('two different passwords are not previewed', async () => {
  const user = userEvent.setup()
  renderTab()
  await user.type(await screen.findByLabelText('New password'), PASSWORD)
  await user.type(screen.getByLabelText('Confirm the password'), `${PASSWORD}x`)
  expect(screen.getByText('The two passwords differ.')).toBeInTheDocument()
  expect(calls.some((c) => c.path.startsWith(`${base}/password`))).toBe(false)
})

test("the app's SSH instance cannot be turned off, removed or moved; a new one applies with rollback", async () => {
  const user = userEvent.setup()
  renderTab()
  const ssh = await screen.findByRole('table', { name: 'SSH instances' })
  const main = within(ssh).getByRole('row', { name: /main/ })
  expect(within(main).getByText('The app connects here')).toBeInTheDocument()
  expect(within(main).getByRole('checkbox', { name: 'Enable main' })).toBeDisabled()
  expect(within(main).getByRole('button', { name: 'Remove main' })).toBeDisabled()
  const where = within(main).getByRole('combobox', { name: 'Interface of main' })
  expect(within(where).getAllByRole('option').map((o) => o.textContent)).toEqual(['All interfaces', 'lan'])
  await user.click(screen.getByRole('button', { name: 'Add instance' }))
  const added = within(ssh).getByRole('row', { name: /new/ })
  const port = within(added).getByRole('spinbutton', { name: 'Port of new 1' })
  await user.clear(port)
  await user.type(port, '2222')
  await within(card('SSH access')).findByRole('region', { name: 'Command preview' })
  expect(calls.at(-1)).toEqual({
    method: 'POST',
    path: `${base}/ssh/preview`,
    body: { instances: [{ section: null, enable: true, port: 2222, interface: '', password_auth: true, root_password_auth: true, gateway_ports: false }], remove: [] },
  })
  expect(within(card('SSH access')).getByRole('button', { name: 'Apply with rollback' })).toBeEnabled()
})

test('a pasted key line previews the authorized_keys heredoc; the app key has no Remove', async () => {
  const user = userEvent.setup()
  renderTab()
  const keys = await screen.findByRole('table', { name: 'SSH keys' })
  const app = within(keys).getByRole('row', { name: /openwrtgui@pc/ })
  expect(within(app).getByText('App')).toBeInTheDocument()
  expect(within(app).queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument()
  expect(within(within(keys).getByRole('row', { name: /bench@lab/ })).getByText('Other')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Add key' }))
  await user.click(screen.getByRole('textbox', { name: 'Public key line' }))
  await user.paste(AP2_NEW_KEY)
  const preview = await within(card('SSH keys')).findByRole('region', { name: 'Command preview' })
  expect(preview).toHaveTextContent("cat > /etc/dropbear/authorized_keys <<'OWG'")
  expect(preview).toHaveTextContent(AP2_NEW_KEY)
  expect(calls.at(-1)).toEqual({ method: 'POST', path: `${base}/ssh-keys/preview`, body: { add: [AP2_NEW_KEY], remove: [] } })
})

test("a harness's owner name is saved and its key is labelled with it", async () => {
  const user = userEvent.setup()
  renderTab()
  const keys = await screen.findByRole('table', { name: 'SSH keys' })
  const other = within(keys).getByRole('row', { name: /bench@lab/ })
  await user.click(within(other).getByRole('button', { name: 'Owner…' }))
  await user.type(screen.getByRole('textbox', { name: 'Owner of bench@lab' }), 'bench-harness')
  await user.click(screen.getByRole('button', { name: 'Save owner' }))
  const fingerprint = AP2_ACCESS.keys[1].fingerprint
  expect(calls.at(-1)).toEqual({ method: 'PUT', path: `${base}/ssh-keys/owner`, body: { fingerprint, owner: 'bench-harness' } })
  expect(await within(within(keys).getByRole('row', { name: /bench@lab/ })).findByText('Harness · bench-harness')).toBeInTheDocument()
})

test('LuCI off the network says the LuCI pages in this app keep working; the redirect needs HTTPS', async () => {
  const user = userEvent.setup()
  renderTab()
  const http = await screen.findByRole('region', { name: 'HTTP(S) access' })
  expect(within(http).getByRole('checkbox', { name: 'Redirect HTTP to HTTPS' })).toBeDisabled() // AP2 serves no HTTPS
  expect(within(http).getByText('AP2 serves no HTTPS: nothing listens on its HTTPS port.')).toBeInTheDocument()
  const luci = within(http).getByRole('checkbox', { name: 'LuCI on the network' })
  expect(luci).toBeChecked()
  await user.click(luci)
  expect(within(http).getByText('Off: only the router itself reaches LuCI. LuCI pages in this app keep working.')).toBeInTheDocument()
  await within(http).findByRole('region', { name: 'Command preview' })
  expect(calls.at(-1)).toEqual({ method: 'POST', path: `${base}/http/preview`, body: { luci_on_network: false } })
})

test('the repository keys are listed by name', async () => {
  renderTab()
  const repo = await screen.findByRole('list', { name: 'Repository keys' })
  expect(within(repo).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['openwrt-snapshots.pem (apk)', 'public-key.pem (apk)'])
})

test("an instance's DirectInterface is shown and kept as it is", async () => {
  access = { ...AP2_ACCESS, ssh: [{ ...AP2_ACCESS.ssh[0], direct_interface: 'br-lan' }] }
  renderTab()
  const main = within(await screen.findByRole('table', { name: 'SSH instances' })).getByRole('row', { name: /main/ })
  expect(within(main).getByText('DirectInterface br-lan (kept as it is)')).toBeInTheDocument()
})
