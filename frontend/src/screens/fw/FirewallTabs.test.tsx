import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import type { FirewallState, GuardOut, NetApplyResult } from '../../api/types'
import { AP1 } from '../../testing/fixtures'
import { AP1_FW, AP1_RULESET, CUSTOM_PLAN, RULE_ADD_PLAN, TABLE_ADD_PLAN, TABLE_EDIT_PLAN } from '../../testing/fw'
import { FirewallScreen } from './FirewallScreen'

const CONFIRMED: NetApplyResult = {
  router_id: 'ap1',
  applied: true,
  verified: true,
  error: null,
  host: null,
  checks: [
    { name: 'reconnected', ok: true, detail: 'AP1 · bench answered at 192.168.1.1' },
    { name: 'confirmed', ok: true, detail: 'the router keeps the change' },
  ],
}
const CLEAR: GuardOut = { live: false, reasons: [], checked_at: '2026-11-06T21:00:00' }
const LIVE: GuardOut = {
  live: true,
  reasons: [{ kind: 'process', detail: 'dima_night.py', pid: 18244, router: null, since: '21:04', text: 'dima_night.py started 21:04 (PID 18244)' }],
  checked_at: '2026-11-06T21:05:00',
}

const calls: Array<{ path: string; body: unknown }> = []
let fw: FirewallState = AP1_FW
let guard: GuardOut = CLEAR

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  const respond = async (path: string, body?: unknown): Promise<unknown> => {
    calls.push({ path, body })
    if (path === '/api/routers/ap1') return AP1
    if (path === '/api/guard') return guard
    if (path === '/api/routers/ap1/firewall') return fw
    if (path === '/api/routers/ap1/firewall/ruleset') return { text: AP1_RULESET }
    if (path === '/api/routers/ap1/luci/pages') return []
    if (path === '/api/routers/ap1/firewall/rules/preview') return RULE_ADD_PLAN
    if (path === '/api/routers/ap1/firewall/custom/preview') return CUSTOM_PLAN
    if (path === '/api/routers/ap1/firewall/tables/preview') return (body as { action: string }).action === 'add' ? TABLE_ADD_PLAN : TABLE_EDIT_PLAN
    if (path.endsWith('/apply')) return CONFIRMED
    throw new Error(`unexpected ${path}`)
  }
  return {
    ...actual,
    apiFetch: vi.fn((path: string) => respond(path)),
    postJson: vi.fn((path: string, body?: unknown) => respond(path, body)),
  }
})

beforeEach(() => {
  calls.length = 0
  fw = AP1_FW
  guard = CLEAR
})

function renderTab(tab: string) {
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[`/routers/ap1/firewall?tab=${tab}`]}>
        <Routes>
          <Route path="/routers/:id/firewall" element={<FirewallScreen />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return user
}

const lastBody = (what: string): unknown => calls.filter((c) => c.path.endsWith(`/firewall/${what}/preview`)).at(-1)?.body

test('+ Rule previews the uci add lines for the new rule', async () => {
  const user = renderTab('rules')
  const rules = await screen.findByRole('table', { name: 'Traffic rules' })
  expect(within(within(rules).getByRole('row', { name: /Allow-Ping/ })).getByText('12')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '+ Rule' }))
  const editor = screen.getByRole('group', { name: 'New rule' })
  await user.type(within(editor).getByLabelText('Name'), 'Block-panel-ping')
  await user.selectOptions(within(editor).getByLabelText('Source zone'), 'lan')
  await user.type(within(editor).getByLabelText('Protocol'), 'icmp')
  await user.type(within(editor).getByLabelText('Source address'), '192.168.1.20')
  await user.selectOptions(within(editor).getByLabelText('Action'), 'DROP')
  expect(await screen.findByRole('region', { name: 'Command preview' })).toHaveTextContent('add firewall rule')
  const body = lastBody('rules') as { upserts: Array<Record<string, unknown>>; deletes: string[] }
  expect(body.upserts[0]).toMatchObject({ section: null, name: 'Block-panel-ping', src: 'lan', dest: null, proto: 'icmp', src_ip: ['192.168.1.20'], target: 'DROP', enabled: true })
  expect(body.deletes).toEqual([])
})

test('a rule is turned off from its row, and Delete sends its section', async () => {
  const user = renderTab('rules')
  const rules = await screen.findByRole('table', { name: 'Traffic rules' })
  const ping = within(rules).getByRole('row', { name: /Allow-Ping/ })
  await user.click(within(ping).getByRole('checkbox', { name: 'Allow-Ping on' }))
  await screen.findByRole('region', { name: 'Command preview' })
  expect((lastBody('rules') as { upserts: Array<Record<string, unknown>> }).upserts[0]).toMatchObject({ section: 'cfg0692bd', name: 'Allow-Ping', enabled: false })
  await user.click(within(ping).getByRole('button', { name: 'Edit' }))
  await user.click(within(screen.getByRole('group', { name: 'Rule Allow-Ping' })).getByRole('button', { name: 'Delete rule' }))
  await vi.waitFor(() => expect(lastBody('rules')).toEqual({ upserts: [], deletes: ['cfg0692bd'] }))
})

test('the pinned SSH rule cannot be edited as a traffic rule', async () => {
  const pin = { ...AP1_FW.conf.rules[0], section: 'owg_pin_ssh', name: 'Allow SSH from this PC', src: 'lan', proto: 'tcp', dest_port: '22', src_ip: ['192.168.1.10'] }
  fw = { ...AP1_FW, conf: { ...AP1_FW.conf, rules: [...AP1_FW.conf.rules, pin] }, rules: [...AP1_FW.rules, { ...AP1_FW.rules[0], conf: pin, zone: 'lan', effect: 'no-effect-allow', packets: 40 }] }
  renderTab('rules')
  const row = within(await screen.findByRole('table', { name: 'Traffic rules' })).getByRole('row', { name: /Allow SSH from this PC/ })
  expect(within(row).getByText('kept open by the app · change it on Zones and model')).toBeInTheDocument()
  expect(within(row).queryByRole('button', { name: 'Edit' })).toBeNull()
  expect(within(row).queryByRole('checkbox')).toBeNull()
})

test('no port forwards shows what one does and what it asks for', async () => {
  renderTab('forwards')
  expect(await screen.findByText('No port forwards on AP1. A port forward sends traffic arriving on wan to a device on lan.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '+ Port forward' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Help: Port forwards' })).toBeInTheDocument()
})

test('a custom rules file edit previews the file and fw4’s check', async () => {
  const user = renderTab('custom')
  const files = await screen.findByRole('table', { name: 'Custom rules files' })
  const row = within(files).getByRole('row', { name: /10-custom-filter-chains/ })
  expect(within(row).getByText('from the image')).toBeInTheDocument()
  expect(within(row).getByText('4 · comments only')).toBeInTheDocument()
  expect(screen.getByText(/Edits are checked with nft -c before fw4 restarts/)).toBeInTheDocument()
  await user.click(within(row).getByRole('button', { name: 'Edit' }))
  const text = screen.getByRole('textbox', { name: 'Rules in 10-custom-filter-chains' })
  await user.clear(text)
  await user.type(text, '# nothing')
  expect(await screen.findByRole('region', { name: 'Command preview' })).toHaveTextContent('nft -c -f /tmp/owg/rb-<rollback>.check')
  expect(lastBody('custom')).toEqual({ name: '10-custom-filter-chains', content: '# nothing' })
})

test('Unlock on voipdscp names its owner and dependency; an edit previews with the override and nft -c; Lock hides it', async () => {
  const user = renderTab('tables')
  const tables = await screen.findByRole('table', { name: 'nftables tables' })
  const row = within(tables).getByRole('row', { name: /bridge voipdscp/ })
  expect(within(row).getByText('harness · voip_chain')).toBeInTheDocument()
  await user.click(within(row).getByRole('button', { name: 'Unlock…' }))
  const ask = screen.getByRole('group', { name: 'Unlock bridge voipdscp?' })
  expect(within(ask).getByText('voip_chain')).toBeInTheDocument()
  expect(within(ask).getByText('VoIP chain runs expect RTP and SIP marked EF. Changing it changes their results.')).toBeInTheDocument()
  expect(within(ask).getByText('no harness run (Bench Guard clear)')).toBeInTheDocument()
  expect(within(ask).getByText(/The override is written to the audit log/)).toBeInTheDocument()
  await user.click(within(ask).getByRole('button', { name: 'Unlock' }))
  const editor = await screen.findByRole('group', { name: 'Table bridge voipdscp' })
  const first = within(editor).getAllByRole('row')[1]
  expect(within(first).getByText('31')).toBeInTheDocument()
  await user.click(within(first).getByRole('button', { name: 'Edit' }))
  const input = within(editor).getByRole('textbox', { name: 'post rule 1' })
  await user.clear(input)
  await user.type(input, 'udp dport 5004 counter')
  expect(await screen.findByRole('region', { name: 'Command preview' })).toHaveTextContent("nft -c -f /dev/stdin <<'OWG'")
  expect(screen.getByText(/written to the audit log as an override/)).toBeInTheDocument()
  expect(lastBody('tables')).toEqual({
    key: 'bridge voipdscp',
    action: 'edit',
    override: true,
    keep: 'runtime',
    rules: [
      { chain: 'post', body: 'udp dport 5004 counter' },
      { chain: 'post', body: 'udp dport { 5060, 5061 } ip dscp set ef counter' },
    ],
  })
  await user.click(within(row).getByRole('button', { name: 'Lock' }))
  expect(screen.queryByRole('group', { name: 'Table bridge voipdscp' })).toBeNull()
  expect(within(row).getByRole('button', { name: 'Unlock…' })).toBeInTheDocument()
})

test('+ Add table previews the new owg_ table', async () => {
  const user = renderTab('tables')
  await screen.findByRole('table', { name: 'nftables tables' })
  await user.click(screen.getByRole('button', { name: '+ Add table' }))
  const add = screen.getByRole('group', { name: 'New table' })
  expect(within(within(add).getByRole('group', { name: 'Table family' })).getByRole('button', { name: 'inet' })).toHaveAttribute('aria-pressed', 'true')
  await user.type(within(add).getByLabelText('Name'), 'test')
  expect(within(add).getByText('owg_test')).toBeInTheDocument()
  expect(await screen.findByRole('region', { name: 'Command preview' })).toHaveTextContent('table inet owg_test {')
  expect(lastBody('tables')).toEqual({ action: 'add', family: 'inet', name: 'test', keep: 'runtime' })
})

test('while Bench Guard is live nothing unlocks', async () => {
  guard = LIVE
  renderTab('tables')
  const tables = await screen.findByRole('table', { name: 'nftables tables' })
  const row = within(tables).getByRole('row', { name: /bridge voipdscp/ })
  expect(await within(row).findByRole('button', { name: 'Locked during run' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '+ Add table' })).toBeDisabled()
})

test('the raw ruleset shows the text and Copy puts it on the clipboard', async () => {
  const user = renderTab('raw')
  const raw = await screen.findByRole('region', { name: 'Raw ruleset text' })
  await vi.waitFor(() => expect(raw).toHaveTextContent('table bridge voipdscp'))
  await user.click(screen.getByRole('button', { name: 'Copy' }))
  expect(await navigator.clipboard.readText()).toBe(AP1_RULESET)
  expect(screen.getByRole('button', { name: 'Help: Raw ruleset' })).toBeInTheDocument()
})

test('the result of a table edit, a new table and a rules file stays after Apply', async () => {
  const user = renderTab('tables')
  const tables = await screen.findByRole('table', { name: 'nftables tables' })
  await user.click(within(within(tables).getByRole('row', { name: /bridge voipdscp/ })).getByRole('button', { name: 'Unlock…' }))
  await user.click(within(screen.getByRole('group', { name: 'Unlock bridge voipdscp?' })).getByRole('button', { name: 'Unlock' }))
  const editor = await screen.findByRole('group', { name: 'Table bridge voipdscp' })
  await user.click(within(within(editor).getAllByRole('row')[1]).getByRole('button', { name: 'Delete' }))
  await screen.findByRole('region', { name: 'Command preview' })
  await user.click(screen.getByRole('button', { name: /^Apply/ }))
  expect(await screen.findByText('Applied and confirmed')).toBeInTheDocument()
  // the table stays unlocked and open for the next edit
  expect(screen.getByRole('group', { name: 'Table bridge voipdscp' })).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: '+ Add table' }))
  await user.type(within(screen.getByRole('group', { name: 'New table' })).getByLabelText('Name'), 'test')
  await screen.findByRole('region', { name: 'Command preview' })
  await user.click(screen.getByRole('button', { name: /^Apply/ }))
  await vi.waitFor(() => expect(screen.queryByRole('group', { name: 'New table' })).toBeNull())
  // the edit's result and the new table's
  expect(screen.getAllByText('Applied and confirmed')).toHaveLength(2)
})

test('the result of a rules file Apply stays after the editor closes', async () => {
  const user = renderTab('custom')
  const row = within(await screen.findByRole('table', { name: 'Custom rules files' })).getByRole('row', { name: /10-custom-filter-chains/ })
  await user.click(within(row).getByRole('button', { name: 'Edit' }))
  await user.type(screen.getByRole('textbox', { name: 'Rules in 10-custom-filter-chains' }), '# more')
  await screen.findByRole('region', { name: 'Command preview' })
  await user.click(screen.getByRole('button', { name: /^Apply/ }))
  await vi.waitFor(() => expect(screen.queryByRole('group', { name: 'File 10-custom-filter-chains' })).toBeNull())
  expect(screen.getByText('Applied and confirmed')).toBeInTheDocument()
})
