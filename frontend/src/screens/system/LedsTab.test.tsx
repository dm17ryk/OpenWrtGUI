import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { AP2_LED_PLAN, AP2_LEDS } from '../../testing/system'
import { LedsTab } from './LedsTab'

const calls: Array<{ path: string; body: unknown }> = []
const base = '/api/routers/ap2/system/leds'

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path === base) return AP2_LEDS
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body?: unknown) => {
      calls.push({ path, body })
      if (path === `${base}/preview`) return AP2_LED_PLAN
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
      <LedsTab routerId="ap2" routerName="AP2 · office" />
    </QueryClientProvider>,
  )
}

test("a trigger change shows that trigger's options and previews the uci lines", async () => {
  const user = userEvent.setup()
  renderTab()
  const trigger = await screen.findByRole('combobox', { name: 'Trigger of led_lan' })
  expect(trigger).toHaveValue('switch0')
  expect(screen.getByRole('combobox', { name: 'LED of led_lan' })).toHaveValue('green:lan')
  expect(screen.getByRole('textbox', { name: 'Port mask of led_lan' })).toHaveValue('0x0f')
  expect(within(trigger).getAllByRole('option').map((o) => o.textContent)).toEqual(AP2_LEDS.leds[3].triggers)
  expect(screen.queryByRole('region', { name: 'Command preview' })).not.toBeInTheDocument()
  await user.selectOptions(trigger, 'netdev')
  expect(screen.queryByRole('textbox', { name: 'Port mask of led_lan' })).not.toBeInTheDocument()
  await user.selectOptions(screen.getByRole('combobox', { name: 'Device of led_lan' }), 'eth0.2')
  for (const mode of ['link', 'tx', 'rx']) await user.click(screen.getByRole('checkbox', { name: `${mode} on led_lan` }))
  const preview = await screen.findByRole('region', { name: 'Command preview' })
  expect(preview).toHaveTextContent("uci set system.led_lan.trigger='netdev'")
  expect(calls.at(-1)).toEqual({
    path: `${base}/preview`,
    body: {
      rows: [
        {
          section: 'led_lan',
          name: 'lan',
          sysfs: 'green:lan',
          trigger: 'netdev',
          default: null,
          delayon: null,
          delayoff: null,
          inverted: null,
          dev: 'eth0.2',
          mode: ['link', 'tx', 'rx'],
          port_mask: null,
          speed_mask: null,
        },
      ],
    },
  })
})

test('an added LED action starts on the first LED with no trigger; Remove takes a row out', async () => {
  const user = userEvent.setup()
  renderTab()
  await user.click(await screen.findByRole('button', { name: 'Add LED action' }))
  expect(screen.getByRole('combobox', { name: 'LED of new 1' })).toHaveValue('green:3g')
  expect(screen.getByRole('combobox', { name: 'Trigger of new 1' })).toHaveValue('none')
  expect(screen.getByRole('checkbox', { name: 'On by default new 1' })).not.toBeChecked()
  await user.click(screen.getByRole('button', { name: 'Remove led_lan' }))
  await screen.findByRole('region', { name: 'Command preview' })
  const last = calls[calls.length - 1]
  expect(last.path).toBe(`${base}/preview`)
  const rows = (last.body as { rows: Array<{ section: string | null; sysfs: string }> }).rows
  expect(rows.map((r) => [r.section, r.sysfs])).toEqual([[null, 'green:3g']]) // led_lan left out: removed
})
