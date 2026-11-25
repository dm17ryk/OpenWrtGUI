import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import type { GuardOut, UssdReply } from '../../api/types'
import { UssdCard } from './UssdCard'

const WARNING = "The app listens up to 35 s for the network's reply; the AT console waits until then"
const RULE =
  'A USSD code looks like *100#: * or #, digits, * or #, ending in #. PIN, PUK, call barring and call forwarding codes, and codes starting with ** or ##, are refused'

let answer: UssdReply | Error | 'pending' = { status: 'reply', text: 'Balance 12.34', dcs: 15, closed: true }
let release: (() => void) | null = null
const posts: Array<{ path: string; body: unknown }> = []

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async () => {
      throw new Error('unexpected read')
    }),
    postJson: vi.fn(async (path: string, body?: unknown) => {
      posts.push({ path, body })
      if (path.endsWith('/preview')) {
        return {
          lines: ['printf AT+CUSD=1 | microcom /dev/ttyUSB2'],
          warnings: [WARNING],
          digest: 'digest-1',
          rollback: false,
          router_id: 'ap2',
          screen: 'lte',
          target_host: null,
        }
      }
      if (answer === 'pending') await new Promise<void>((resolve) => (release = resolve))
      if (answer === 'pending') return { status: 'reply', text: 'Balance 12.34', dcs: 15, closed: true }
      if (answer instanceof Error) throw answer
      return answer
    }),
  }
})

const CLEAR: GuardOut = { live: false, reasons: [], checked_at: '2026-11-25T12:00:00' }
const LIVE = {
  live: true,
  reasons: [{ kind: 'process', text: 'TXCTL v14 night run', detail: 'pytest' }],
  checked_at: '2026-11-25T12:00:00',
} as GuardOut

beforeEach(() => {
  answer = { status: 'reply', text: 'Balance 12.34', dcs: 15, closed: true }
  release = null
  posts.length = 0
})

function renderUssd(guard: GuardOut = CLEAR) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['guard'], guard)
  render(
    <QueryClientProvider client={client}>
      <UssdCard routerId="ap2" routerName="AP2 · office" />
    </QueryClientProvider>,
  )
}

async function send(code: string) {
  const user = userEvent.setup()
  await user.type(screen.getByRole('textbox', { name: 'USSD code' }), code)
  await user.click(screen.getByRole('button', { name: 'Preview' }))
  await screen.findByText(WARNING) // the preview has arrived, so Send USSD is enabled
  await user.click(screen.getByRole('button', { name: 'Send USSD' }))
  return user
}

test('the card has a code field, its help button, and Preview waits for a valid code', async () => {
  renderUssd()
  expect(screen.getByRole('heading', { name: 'USSD', level: 2 })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Help: USSD' })).toBeInTheDocument()
  const user = userEvent.setup()
  const preview = screen.getByRole('button', { name: 'Preview' })
  expect(preview).toBeDisabled()
  await user.type(screen.getByRole('textbox', { name: 'USSD code' }), '100')
  expect(screen.getByText(RULE)).toBeInTheDocument()
  expect(preview).toBeDisabled()
  await user.type(screen.getByRole('textbox', { name: 'USSD code' }), '#')
  expect(preview).toBeDisabled() // "100#" does not start with * or #
})

test.each(['**04*1234*5678*5678#', '*33*0000#', '##002#', '**21*15550101#', '*21#', '#21#', '*#31#', '*21*0501234567#', '*43#'])(
  'a PIN, call barring or ** / ## code %s is refused with the rule and never previewed',
  async (code) => {
    renderUssd()
    const user = userEvent.setup()
    await user.type(screen.getByRole('textbox', { name: 'USSD code' }), code)
    expect(screen.getByText(RULE)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled()
    expect(posts).toEqual([])
  },
)

test.each(['*100#', '#100#', '*#100#', '*111#', '*#06#', '*300#', '*210#', '*43210#'])('the ordinary code %s can be previewed', async (code) => {
  renderUssd()
  await userEvent.setup().type(screen.getByRole('textbox', { name: 'USSD code' }), code)
  expect(screen.queryByText(RULE)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Preview' })).toBeEnabled()
})

test('Preview shows the listening warning and sends nothing to the network', async () => {
  renderUssd()
  const user = userEvent.setup()
  await user.type(screen.getByRole('textbox', { name: 'USSD code' }), '*100#')
  await user.click(screen.getByRole('button', { name: 'Preview' }))
  expect(await screen.findByText(WARNING)).toBeInTheDocument()
  expect(posts.map((p) => p.path)).toEqual(['/api/routers/ap2/lte/ussd/preview'])
  expect(posts[0]?.body).toEqual({ code: '*100#' })
})

test('while the apply runs it says it is listening, then shows the reply', async () => {
  answer = 'pending'
  renderUssd()
  await send('*100#')
  expect(await screen.findByText("Listening for the network's reply (up to 35 s)…")).toBeInTheDocument()
  release?.()
  expect(await screen.findByText('Balance 12.34')).toBeInTheDocument()
  expect(screen.queryByText("Listening for the network's reply (up to 35 s)…")).not.toBeInTheDocument()
  expect(posts[1]).toEqual({ path: '/api/routers/ap2/lte/ussd/apply', body: { code: '*100#', digest: 'digest-1' } })
})

test('"more" says menus are not supported and the session was closed', async () => {
  answer = { status: 'more', text: 'Reply 1 for A', dcs: 15, closed: true }
  renderUssd()
  await send('*111#')
  expect(await screen.findByText('The network asked for more; menus are not supported, so the session was closed')).toBeInTheDocument()
})

test('"no reply" says the session was closed after 35 s', async () => {
  answer = { status: 'no reply', text: null, dcs: null, closed: true }
  renderUssd()
  await send('*300#')
  expect(await screen.findByText('No reply in 35 s; the session was closed')).toBeInTheDocument()
})

test('"more" with a failed close says the session may still be open', async () => {
  answer = { status: 'more', text: 'Reply 1 for A', dcs: 15, closed: false }
  renderUssd()
  await send('*111#')
  expect(
    await screen.findByText('The network asked for more; menus are not supported, and closing the session failed: it may still be open'),
  ).toBeInTheDocument()
})

test('"no reply" with a failed close says the session may still be open', async () => {
  answer = { status: 'no reply', text: null, dcs: null, closed: false }
  renderUssd()
  await send('*300#')
  expect(await screen.findByText('No reply in 35 s, and closing the session failed: it may still be open')).toBeInTheDocument()
})

test('the code field and Preview are disabled while the apply listens, and editable after', async () => {
  answer = 'pending'
  renderUssd()
  const user = await send('*100#')
  const field = screen.getByRole('textbox', { name: 'USSD code' })
  expect(await screen.findByText("Listening for the network's reply (up to 35 s)…")).toBeInTheDocument()
  expect(field).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled()
  release?.()
  expect(await screen.findByText('Balance 12.34')).toBeInTheDocument()
  expect(field).toBeEnabled()
  await user.type(field, '1')
  expect(field).toHaveValue('*100#1')
})

test('"error" shows the modem error line as an alert', async () => {
  answer = { status: 'error', text: '+CME ERROR: 30', dcs: null, closed: true }
  renderUssd()
  await send('*400#')
  expect(await screen.findByRole('alert')).toHaveTextContent('+CME ERROR: 30')
})

test('"ended" shows the network ending the session', async () => {
  answer = { status: 'ended', text: 'Goodbye', dcs: 15, closed: true }
  renderUssd()
  await send('*500#')
  expect(await screen.findByText('Goodbye')).toBeInTheDocument()
  expect(screen.getByText('The network ended the session')).toBeInTheDocument()
})

test('a failed apply shows the API error', async () => {
  const { ApiError } = await import('../../api/client')
  answer = new ApiError(409, 'busy', null)
  renderUssd()
  await send('*100#')
  expect(await screen.findByText('busy')).toBeInTheDocument()
})

test('during a harness run Preview waits and says why', async () => {
  renderUssd(LIVE)
  await userEvent.setup().type(screen.getByRole('textbox', { name: 'USSD code' }), '*100#')
  const preview = screen.getByRole('button', { name: 'Preview' })
  expect(preview).toBeDisabled()
  expect(preview.getAttribute('title')).toContain('Waits for the run:')
})
