import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import type { DiscoveryState } from '../../api/types'
import { AP1_DISCOVERY, AP2_CHECKLIST, COPY_PLAN } from '../../testing/discovery'
import { ROUTERS } from '../../testing/fixtures'
import { ConfigSection } from './ConfigSection'
import { OverlaySection } from './OverlaySection'

const calls: Array<{ path: string; body?: unknown }> = []

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  const respond = async (path: string, body?: unknown): Promise<unknown> => {
    calls.push({ path, body })
    if (path === '/api/routers') return ROUTERS
    if (path === '/api/routers/ap1/discovery/copy/preview') return COPY_PLAN
    if (path === '/api/routers/ap1/discovery/copy/apply') {
      return { router_id: 'ap2', applied: true, verified: true, checks: [], error: null, host: '192.168.1.2' }
    }
    if (path === '/api/routers/ap1/discovery/checklist') return AP2_CHECKLIST
    throw new Error(`unexpected ${path}`)
  }
  return {
    ...actual,
    apiFetch: vi.fn((path: string) => respond(path)),
    postJson: vi.fn((path: string, body?: unknown) => respond(path, body ?? {})),
  }
})

beforeEach(() => {
  calls.length = 0
})

function renderWith(ui: React.ReactElement) {
  const user = userEvent.setup()
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)
  return user
}

test('lists added, changed and deleted with what a flash keeps', () => {
  renderWith(<OverlaySection routerId="ap1" state={AP1_DISCOVERY} />)
  const mirror = screen.getByText('/usr/sbin/wifi-mirror').closest('li') as HTMLElement
  expect(within(mirror).getByText('lost on a flash')).toBeVisible()
  const dropbear = screen.getByText('/etc/config/dropbear').closest('li') as HTMLElement
  expect(within(dropbear).getByText('kept on a flash')).toBeVisible()
  expect(screen.getByText('/etc/uci-defaults/20_dwr921_c3_uboot_luci')).toBeVisible()
  expect(screen.getByText(/iperf3 3\.17\.1-r2/)).toBeVisible()
})

test('says so when what a flash keeps could not be read', () => {
  const state: DiscoveryState = { ...AP1_DISCOVERY, kept_on_flash: [], kept_known: false }
  renderWith(<OverlaySection routerId="ap1" state={state} />)
  expect(screen.getByText(/Could not read what a flash keeps/)).toBeVisible()
  const mirror = screen.getByText('/usr/sbin/wifi-mirror').closest('li') as HTMLElement
  expect(within(mirror).getByText('kept or lost: unknown')).toBeVisible()
  expect(screen.queryByText('lost on a flash')).not.toBeInTheDocument()
})

test('counts names that could not be read', () => {
  const state: DiscoveryState = { ...AP1_DISCOVERY, overlay: { ...AP1_DISCOVERY.overlay, unreadable: 1 } }
  renderWith(<OverlaySection routerId="ap1" state={state} />)
  expect(screen.getByText('1 name could not be read')).toBeVisible()
})

test('copies ticked files through the preview', async () => {
  const user = renderWith(<OverlaySection routerId="ap1" state={AP1_DISCOVERY} />)
  await user.click(screen.getByRole('checkbox', { name: '/usr/sbin/wifi-mirror' }))
  await user.selectOptions(await screen.findByLabelText('Copy to'), 'ap2')
  expect(await screen.findByRole('region', { name: 'Command preview' })).toHaveTextContent(COPY_PLAN.lines[0], {
    normalizeWhitespace: false,
  })
  await user.click(screen.getByRole('button', { name: 'Copy' }))
  const applied = calls.find((c) => c.path.endsWith('/copy/apply'))
  expect(applied?.body).toEqual({ paths: ['/usr/sbin/wifi-mirror'], target: 'ap2', digest: COPY_PLAN.digest })
})

test('saves a reflash checklist', async () => {
  const user = renderWith(<OverlaySection routerId="ap1" state={AP1_DISCOVERY} />)
  await user.click(screen.getByRole('button', { name: 'Save as reflash checklist' }))
  expect(await screen.findByText('Saved: 2 files lost on a flash')).toBeVisible()
})

test('shows first-boot configs without a diff, and a config diff', () => {
  renderWith(<ConfigSection state={AP1_DISCOVERY} />)
  expect(screen.getByText('network: created at first boot (not in the image)')).toBeVisible()
  const row = screen.getByText('dropbear.@dropbear[0].Port').closest('tr') as HTMLElement
  expect(within(row).getByText('22')).toBeVisible()
  expect(within(row).getByText('2222')).toBeVisible()
})
