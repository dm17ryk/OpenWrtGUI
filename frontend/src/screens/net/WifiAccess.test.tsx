import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import type { AccessState, NetPlan } from '../../api/types'
import { ACCESS, SAVED_BLOCK_PLAN } from '../../testing/net'
import { WifiAccess } from './WifiAccess'

const calls: Array<{ path: string; body: unknown }> = []
let preview: NetPlan | { refuse: string } = SAVED_BLOCK_PLAN
let access: AccessState = ACCESS

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  const respond = async (path: string, body?: unknown): Promise<unknown> => {
    calls.push({ path, body })
    if (path === '/api/routers/ap2/network/access') return access
    if (path === '/api/routers/ap2/network/access/preview') {
      if ('refuse' in preview) throw new actual.ApiError(422, preview.refuse, {})
      return preview
    }
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
  preview = SAVED_BLOCK_PLAN
  access = ACCESS
})

function renderAccess() {
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <WifiAccess routerId="ap2" routerName="AP2 · office" onApplied={() => {}} />
    </QueryClientProvider>,
  )
  return user
}

const lastBody = (): unknown => calls.filter((c) => c.path.endsWith('/access/preview')).at(-1)?.body

test('Only listed with an empty list shows the refusal', async () => {
  preview = { refuse: 'Add a device to the list before choosing Only listed: an empty list keeps every device off lab-open.' }
  const user = renderAccess()
  const policy = await screen.findByRole('group', { name: 'Who may join' })
  expect(within(policy).getByRole('button', { name: 'Everyone' })).toHaveAttribute('aria-pressed', 'false')
  await user.click(within(policy).getByRole('button', { name: 'Only listed' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('an empty list keeps every device off lab-open')
  expect(lastBody()).toEqual({ kind: 'policy', sections: ['default_radio0', 'wifinet1'], policy: 'allow' })
})

test('Block now on a parked SSID shows the refusal', async () => {
  preview = { refuse: 'lab-iot is not on air; a block now needs the radio up. Use For N s or Saved.' }
  const user = renderAccess()
  await user.click(await screen.findByRole('checkbox', { name: 'lab-open' }))
  expect(screen.getByText('not on air')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Block sta-1' }))
  expect(screen.getByText('Until the next Wi-Fi restart.')).toBeInTheDocument()
  expect(await screen.findByRole('alert')).toHaveTextContent('lab-iot is not on air')
  expect(lastBody()).toEqual({ kind: 'block', sections: ['wifinet1'], mac: 'e4:5f:01:aa:bb:01', method: 'now' })
})

test('a saved block on an Everyone SSID shows the policy warning', async () => {
  const user = renderAccess()
  await user.click(await screen.findByRole('checkbox', { name: 'lab-iot' }))
  await user.click(screen.getByRole('button', { name: 'Block sta-1' }))
  await user.click(screen.getByRole('button', { name: 'Saved' }))
  expect(await screen.findByText('lab-open changes from Everyone to Block listed.')).toBeInTheDocument()
  expect(lastBody()).toEqual({ kind: 'block', sections: ['default_radio0'], mac: 'e4:5f:01:aa:bb:01', method: 'saved' })
})

test('a name given with + Device stays when the router lists that MAC without a name', async () => {
  access = { ...ACCESS, devices: [...ACCESS.devices, { mac: '02:00:00:00:ca:fe', name: null, saved_in: [], blocked_now_on: ['wlan0'] }] }
  const user = renderAccess()
  await user.click(await screen.findByRole('button', { name: '+ Device' }))
  await user.type(screen.getByRole('textbox', { name: 'New device MAC' }), '02:00:00:00:CA:FE')
  await user.type(screen.getByRole('textbox', { name: 'New device name' }), 'cam')
  await user.click(screen.getByRole('button', { name: 'Add' }))
  const row = within(screen.getByRole('table', { name: 'Devices' })).getByRole('row', { name: /02:00:00:00:ca:fe/ })
  expect(row).toHaveTextContent('cam')
  expect(row).toHaveTextContent('wlan0')
  expect(within(row).getByRole('button', { name: 'Unblock cam' })).toBeInTheDocument()
})

test('a block for N s sends the seconds', async () => {
  const user = renderAccess()
  await user.click(await screen.findByRole('checkbox', { name: 'lab-iot' }))
  await user.click(screen.getByRole('button', { name: 'Block sta-1' }))
  await user.click(screen.getByRole('button', { name: 'For 60 s' }))
  const seconds = screen.getByRole('spinbutton', { name: 'Seconds' })
  await user.clear(seconds)
  await user.type(seconds, '300')
  await screen.findByRole('region', { name: 'Command preview' })
  expect(lastBody()).toEqual({ kind: 'block', sections: ['default_radio0'], mac: 'e4:5f:01:aa:bb:01', method: 'timed', seconds: 300 })
})
