import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import type { GuardOut } from '../../api/types'
import { LTE_AT_CFUN, LTE_AT_CSQ } from '../../testing/lte'
import { AtConsole, RISKY_QUESTION } from './AtConsole'

const calls: Array<{ path: string; body: unknown }> = []
let hold: Promise<void> | null = null

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
      const { command, confirmed } = body as { command: string; confirmed: boolean }
      if (command === 'AT+CSQ' || command === 'AT+CPIN=?') return LTE_AT_CSQ
      if (!confirmed) {
        if (hold) await hold // a slow answer: the person may type meanwhile
        // the server's 428 (spec 4.5): its own rule decides `risky`
        const risky = /^AT(&[FW]|\+CFUN=)/i.test(command)
        throw new actual.ApiError(428, 'This command may change the modem; send it again with confirm', { risky })
      }
      return LTE_AT_CFUN
    }),
  }
})

const CLEAR: GuardOut = { live: false, reasons: [], checked_at: '2026-11-08T12:00:00' }
const LIVE = { live: true, reasons: [{ kind: 'process', text: 'TXCTL v14 night run', detail: 'pytest' }], checked_at: '2026-11-08T12:00:00' } as GuardOut

beforeEach(() => {
  calls.length = 0
  hold = null
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

const AT = '/api/routers/ap2/lte/at'

test('a command that may change the modem goes unconfirmed first, asks on the 428, then sends confirmed', async () => {
  const user = userEvent.setup()
  const { input, send } = renderConsole()
  await user.type(input, 'AT+COPS=0')
  await user.click(send)
  const ask = await screen.findByRole('group', { name: 'Confirm AT command' })
  expect(calls).toEqual([{ path: AT, body: { command: 'AT+COPS=0', confirmed: false } }])
  expect(ask).toHaveTextContent('This command may change the modem. Send it?')
  await user.click(within(ask).getByRole('button', { name: 'Send' }))
  expect(calls.at(-1)).toEqual({ path: AT, body: { command: 'AT+COPS=0', confirmed: true } })
  expect(screen.queryByRole('group', { name: 'Confirm AT command' })).not.toBeInTheDocument()
})

test('a risky command asks the stronger question', async () => {
  const user = userEvent.setup()
  const { input, send } = renderConsole()
  await user.type(input, 'AT+CFUN=0')
  await user.click(send)
  const ask = await screen.findByRole('group', { name: 'Confirm AT command' })
  expect(ask).toHaveTextContent(RISKY_QUESTION)
  await user.click(within(ask).getByRole('button', { name: 'Send' }))
  expect(calls.at(-1)).toEqual({ path: AT, body: { command: 'AT+CFUN=0', confirmed: true } })
})

test('Send after the question sends the command it asked about, not text typed meanwhile', async () => {
  // final review: editing AT+COPS=0 into AT&F during the unconfirmed round trip must not send AT&F under the
  // generic question
  const user = userEvent.setup()
  let answer = (): void => {}
  hold = new Promise<void>((resolve) => {
    answer = resolve
  })
  const { input, send } = renderConsole()
  await user.type(input, 'AT+COPS=0')
  await user.click(send)
  await user.clear(input)
  await user.type(input, 'AT&F') // typed while the server's 428 for AT+COPS=0 is on its way
  answer()
  await new Promise((r) => setTimeout(r, 0))
  const ask = screen.queryByRole('group', { name: 'Confirm AT command' })
  if (ask) await user.click(within(ask).getByRole('button', { name: 'Send' }))
  const confirmed = calls.filter((c) => (c.body as { confirmed: boolean }).confirmed).map((c) => (c.body as { command: string }).command)
  expect(confirmed).not.toContain('AT&F')
})

test('a query is sent once, with no question', async () => {
  const user = userEvent.setup()
  const { input, send } = renderConsole()
  await user.type(input, 'AT+CSQ')
  await user.click(send)
  await screen.findByText('+CSQ: 20,99')
  expect(calls).toHaveLength(1)
  expect(screen.queryByRole('group', { name: 'Confirm AT command' })).not.toBeInTheDocument()
})

test('Cancel sends nothing more', async () => {
  const user = userEvent.setup()
  const { input, send } = renderConsole()
  await user.type(input, 'AT+CFUN=0')
  await user.click(send)
  await user.click(within(await screen.findByRole('group', { name: 'Confirm AT command' })).getByRole('button', { name: 'Cancel' }))
  expect(calls).toEqual([{ path: AT, body: { command: 'AT+CFUN=0', confirmed: false } }])
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

test('a SIM PIN is shown hidden and never recalled with Up', async () => {
  const user = userEvent.setup()
  const { input, send } = renderConsole()
  await user.type(input, 'AT+CPIN=1234')
  await user.click(send)
  await user.click(within(await screen.findByRole('group', { name: 'Confirm AT command' })).getByRole('button', { name: 'Send' }))
  expect(calls.at(-1)).toEqual({ path: AT, body: { command: 'AT+CPIN=1234', confirmed: true } })
  const log = await screen.findByRole('log', { name: 'AT console output' })
  expect(within(log).getByText('> AT+CPIN=<hidden>')).toBeInTheDocument()
  expect(log).not.toHaveTextContent('1234')
  await user.click(input)
  await user.keyboard('{ArrowUp}')
  expect(input).toHaveValue('')
})

test('a SIM PIN typed with spaces is hidden too', async () => {
  const user = userEvent.setup()
  const { input, send } = renderConsole()
  await user.type(input, 'AT + CPIN = 1234')
  await user.click(send)
  await user.click(within(await screen.findByRole('group', { name: 'Confirm AT command' })).getByRole('button', { name: 'Send' }))
  const log = await screen.findByRole('log', { name: 'AT console output' })
  expect(log).not.toHaveTextContent('1234')
  await user.click(input)
  await user.keyboard('{ArrowUp}')
  expect(input).toHaveValue('')
})

test('an APN password is hidden and not recalled; a query of it stays readable', async () => {
  const user = userEvent.setup()
  const { input, send } = renderConsole()
  await user.type(input, 'AT+CGAUTH=1,1,"bench","apnpw42"')
  await user.click(send)
  await user.click(within(await screen.findByRole('group', { name: 'Confirm AT command' })).getByRole('button', { name: 'Send' }))
  const log = await screen.findByRole('log', { name: 'AT console output' })
  expect(log).not.toHaveTextContent('apnpw42')
  expect(within(log).getByText('> AT+CGAUTH=<hidden>')).toBeInTheDocument()
  await user.type(input, 'AT+CPIN=?')
  await user.click(send)
  expect(await within(log).findByText('> AT+CPIN=?')).toBeInTheDocument()
  await user.click(input)
  await user.keyboard('{ArrowUp}')
  expect(input).toHaveValue('AT+CPIN=?')
  await user.keyboard('{ArrowUp}')
  expect(input).toHaveValue('AT+CPIN=?')
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
