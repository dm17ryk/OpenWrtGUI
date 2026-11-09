import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import type { GuardOut } from '../../api/types'
import { LTE_AT_CFUN, LTE_AT_CSQ } from '../../testing/lte'
import { AtConsole } from './AtConsole'

const calls: Array<{ path: string; body: unknown }> = []

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body?: unknown) => {
      calls.push({ path, body })
      if (path !== '/api/routers/ap2/lte/at') throw new Error(`unexpected ${path}`)
      return (body as { command: string }).command === 'AT+CSQ' ? LTE_AT_CSQ : LTE_AT_CFUN
    }),
  }
})

const CLEAR: GuardOut = { live: false, reasons: [], checked_at: '2026-11-08T12:00:00' }
const LIVE = { live: true, reasons: [{ kind: 'process', text: 'TXCTL v14 night run', detail: 'pytest' }], checked_at: '2026-11-08T12:00:00' } as GuardOut

beforeEach(() => {
  calls.length = 0
})

function renderConsole(guard: GuardOut = CLEAR) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['guard'], guard)
  render(
    <QueryClientProvider client={client}>
      <AtConsole routerId="ap2" />
    </QueryClientProvider>,
  )
  return { input: screen.getByRole('textbox', { name: 'AT command' }), send: screen.getByRole('button', { name: 'Send' }) }
}

test('a query prints the modem lines and OK', async () => {
  const user = userEvent.setup()
  const { input, send } = renderConsole()
  await user.type(input, 'AT+CSQ')
  await user.click(send)
  expect(calls).toEqual([{ path: '/api/routers/ap2/lte/at', body: { command: 'AT+CSQ', confirmed: false } }])
  const log = await screen.findByRole('log', { name: 'AT console output' })
  expect(await within(log).findByText('+CSQ: 20,99')).toBeInTheDocument()
  expect(within(log).getByText('OK')).toBeInTheDocument()
  expect(input).toHaveValue('')
  expect(screen.getByRole('button', { name: 'Help: AT console' })).toBeInTheDocument()
})

test('a command that may change the modem asks first and sends confirmed on Send', async () => {
  const user = userEvent.setup()
  const { input, send } = renderConsole()
  await user.type(input, 'AT+CFUN=0')
  await user.click(send)
  expect(calls).toEqual([])
  const ask = screen.getByRole('group', { name: 'Confirm AT command' })
  expect(ask).toHaveTextContent('This command may change the modem. Send it?')
  await user.click(within(ask).getByRole('button', { name: 'Send' }))
  expect(calls).toEqual([{ path: '/api/routers/ap2/lte/at', body: { command: 'AT+CFUN=0', confirmed: true } }])
  expect(screen.queryByRole('group', { name: 'Confirm AT command' })).not.toBeInTheDocument()
})

test('Cancel sends nothing', async () => {
  const user = userEvent.setup()
  const { input, send } = renderConsole()
  await user.type(input, 'AT+CFUN=0')
  await user.click(send)
  await user.click(within(screen.getByRole('group', { name: 'Confirm AT command' })).getByRole('button', { name: 'Cancel' }))
  expect(calls).toEqual([])
  expect(input).toHaveValue('AT+CFUN=0')
})

test('during a run a command that may change the modem is disabled and a query is not', async () => {
  const user = userEvent.setup()
  const { input, send } = renderConsole(LIVE)
  await user.type(input, 'AT+CFUN=0')
  expect(send).toBeDisabled()
  expect(screen.getByText(/waits for the run/)).toBeInTheDocument()
  await user.clear(input)
  await user.type(input, 'AT+CSQ')
  expect(send).toBeEnabled()
})

test('Up recalls the last command and Down goes back to an empty line', async () => {
  const user = userEvent.setup()
  const { input, send } = renderConsole()
  await user.type(input, 'AT+CSQ')
  await user.click(send)
  await screen.findByText('+CSQ: 20,99')
  await user.click(input)
  await user.keyboard('{ArrowUp}')
  expect(input).toHaveValue('AT+CSQ')
  await user.keyboard('{ArrowDown}')
  expect(input).toHaveValue('')
})
