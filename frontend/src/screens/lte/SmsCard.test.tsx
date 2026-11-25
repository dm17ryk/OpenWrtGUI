import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import type { GuardOut, SmsDone, SmsList, SmsMessage } from '../../api/types'
import { SmsCard } from './SmsCard'

const BASE = '/api/routers/ap2/lte/sms'
const SIM: SmsList = { storage: 'sim', ids: [1, 2, 3], used: 3, capacity: 20, full: false }
const ME: SmsList = { storage: 'me', ids: [7], used: 1, capacity: 100, full: false }
const GSM_RULE = 'An SMS is 1 to 160 characters of the GSM basic set (letters, digits, common punctuation)'
const NUMBER_RULE = 'A number is digits with an optional + (3 to 15)'
const STALE = 'The message list changed; preview again'

let lists: Record<string, SmsList> = {}
let applyAnswer: SmsDone | Error = { ok: true, lines: [], error: null }
const posts: Array<{ path: string; body: unknown }> = []
const listReads: string[] = []

function plan(path: string) {
  return {
    lines: [`uqmi -d /dev/cdc-wdm0 ${path.split('/').slice(-2).join(' ')}`],
    warnings: path.includes('/send/') ? ["This sends an SMS from the router's SIM to +15550101; the carrier may charge for it"] : [],
    digest: 'digest-1',
    rollback: false,
    router_id: 'ap2',
    screen: 'lte',
    target_host: null,
  }
}

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      const list = /^\/api\/routers\/ap2\/lte\/sms\?storage=(sim|me)$/.exec(path)
      if (list) {
        listReads.push(list[1]!)
        return lists[list[1]!]
      }
      const one = /^\/api\/routers\/ap2\/lte\/sms\/(sim|me)\/(\d+)$/.exec(path)
      if (one) {
        const message: SmsMessage = {
          id: Number(one[2]),
          storage: one[1] as 'sim' | 'me',
          sender: '+15550102',
          time: '2026-11-25 10:00',
          text: `Test message ${one[2]}`,
          part: null,
        }
        return message
      }
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body?: unknown) => {
      posts.push({ path, body })
      if (path.endsWith('/preview')) return plan(path)
      if (path.endsWith('/apply')) {
        if (applyAnswer instanceof Error) throw applyAnswer
        return applyAnswer
      }
      throw new Error(`unexpected ${path}`)
    }),
  }
})

const CLEAR: GuardOut = { live: false, reasons: [], checked_at: '2026-11-25T12:00:00' }
const LIVE: GuardOut = {
  live: true,
  reasons: [{ kind: 'process', text: 'TXCTL v14 night run', detail: 'pytest' }],
  checked_at: '2026-11-25T12:00:00',
} as GuardOut

beforeEach(() => {
  lists = { sim: SIM, me: ME }
  applyAnswer = { ok: true, lines: ['done'], error: null }
  posts.length = 0
  listReads.length = 0
})

function renderSms(guard: GuardOut = CLEAR) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['guard'], guard)
  render(
    <QueryClientProvider client={client}>
      <SmsCard routerId="ap2" routerName="AP2 · office" />
    </QueryClientProvider>,
  )
  return client
}

test('the card has a storage choice and a counts line', async () => {
  const user = userEvent.setup()
  renderSms()
  expect(await screen.findByRole('region', { name: 'SMS' })).toBeInTheDocument()
  const group = screen.getByRole('group', { name: 'SMS storage' })
  expect(within(group).getByRole('button', { name: 'SIM' })).toHaveAttribute('aria-pressed', 'true')
  expect(await screen.findByText('3 of 20 on the SIM')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Help: SMS' })).toBeInTheDocument()
  await user.click(within(group).getByRole('button', { name: 'Phone memory' }))
  expect(await screen.findByText('1 of 100 in the phone memory')).toBeInTheDocument()
})

test('a full SIM says new messages cannot arrive', async () => {
  lists = { ...lists, sim: { ...SIM, ids: [1], used: 20, full: true } }
  renderSms()
  expect(await screen.findByText('SIM full: new messages cannot arrive until some are deleted')).toBeInTheDocument()
})

test('Read shows the sender, time and text in a region for that message', async () => {
  const user = userEvent.setup()
  renderSms()
  await screen.findByText('3 of 20 on the SIM')
  await user.click(screen.getAllByRole('button', { name: 'Read' })[0]!)
  const region = await screen.findByRole('region', { name: 'Message 1' })
  expect(region).toHaveTextContent('+15550102')
  expect(region).toHaveTextContent('2026-11-25 10:00')
  expect(region).toHaveTextContent('Test message 1')
})

test('ticking two rows enables Delete 2 messages, which previews and applies with the digest', async () => {
  const user = userEvent.setup()
  const client = renderSms()
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  await screen.findByText('3 of 20 on the SIM')
  expect(screen.queryByRole('button', { name: /^Delete \d/ })).not.toBeInTheDocument()
  await user.click(screen.getByRole('checkbox', { name: 'Select message 1' }))
  await user.click(screen.getByRole('checkbox', { name: 'Select message 3' }))
  const button = await screen.findByRole('button', { name: 'Delete 2 messages' })
  await waitFor(() => expect(button).toBeEnabled())
  expect(posts).toContainEqual({ path: `${BASE}/delete/preview`, body: { storage: 'sim', ids: [1, 3] } })
  await user.click(button)
  await waitFor(() =>
    expect(posts).toContainEqual({ path: `${BASE}/delete/apply`, body: { storage: 'sim', ids: [1, 3], digest: 'digest-1' } }),
  )
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['lte-sms', 'ap2', 'sim'] }))
  expect(await screen.findByText('Deleted')).toBeInTheDocument()
  expect(screen.queryAllByRole('checkbox', { checked: true })).toHaveLength(0)
})

test('a partly done delete still reads the list again and shows the failure', async () => {
  const user = userEvent.setup()
  applyAnswer = { ok: false, lines: ['deleted 1'], error: 'The modem refused message 3' }
  const client = renderSms()
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  await screen.findByText('3 of 20 on the SIM')
  await user.click(screen.getByRole('checkbox', { name: 'Select message 1' }))
  await user.click(screen.getByRole('checkbox', { name: 'Select message 3' }))
  const button = await screen.findByRole('button', { name: 'Delete 2 messages' })
  await waitFor(() => expect(button).toBeEnabled())
  await user.click(button)
  expect(await screen.findByText('The modem refused message 3')).toBeInTheDocument()
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['lte-sms', 'ap2', 'sim'] }))
  expect(screen.queryAllByRole('checkbox', { checked: true })).toHaveLength(0)
})

test('a 409 shows its text, clears the ticks and reads the list again', async () => {
  const user = userEvent.setup()
  const { ApiError } = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  applyAnswer = new ApiError(409, STALE, {})
  renderSms()
  await screen.findByText('3 of 20 on the SIM')
  await user.click(screen.getByRole('checkbox', { name: 'Select message 2' }))
  const button = await screen.findByRole('button', { name: 'Delete 1 message' })
  await waitFor(() => expect(button).toBeEnabled())
  const reads = listReads.length
  await user.click(button)
  expect(await screen.findByRole('alert')).toHaveTextContent(STALE)
  await waitFor(() => expect(listReads.length).toBeGreaterThan(reads))
  expect(screen.queryAllByRole('checkbox', { checked: true })).toHaveLength(0)
})

test('the send form counts characters and previews, then sends with the digest', async () => {
  const user = userEvent.setup()
  renderSms()
  await screen.findByText('3 of 20 on the SIM')
  const form = screen.getByRole('group', { name: 'Send SMS' })
  await user.type(within(form).getByLabelText('Number'), '+15550101')
  await user.type(within(form).getByLabelText('Text'), 'Test message')
  expect(within(form).getByText('12 / 160')).toBeInTheDocument()
  await user.click(within(form).getByRole('button', { name: 'Preview' }))
  expect(await screen.findByText(/the carrier may charge for it/)).toBeInTheDocument()
  expect(posts).toContainEqual({ path: `${BASE}/send/preview`, body: { target: '+15550101', text: 'Test message' } })
  await user.click(await screen.findByRole('button', { name: 'Send' }))
  await waitFor(() =>
    expect(posts).toContainEqual({
      path: `${BASE}/send/apply`,
      body: { target: '+15550101', text: 'Test message', digest: 'digest-1' },
    }),
  )
  expect(await screen.findByText('SMS sent')).toBeInTheDocument()
  expect(within(form).getByLabelText('Text')).toHaveValue('')
})

test('a character outside the GSM set shows the rule and disables Preview', async () => {
  const user = userEvent.setup()
  renderSms()
  await screen.findByText('3 of 20 on the SIM')
  const form = screen.getByRole('group', { name: 'Send SMS' })
  await user.type(within(form).getByLabelText('Number'), '+15550101')
  await user.type(within(form).getByLabelText('Text'), 'Cost 5$')
  expect(within(form).getByText(GSM_RULE)).toBeInTheDocument()
  expect(within(form).getByRole('button', { name: 'Preview' })).toBeDisabled()
})

test('a bad number shows the number rule and disables Preview', async () => {
  const user = userEvent.setup()
  renderSms()
  await screen.findByText('3 of 20 on the SIM')
  const form = screen.getByRole('group', { name: 'Send SMS' })
  await user.type(within(form).getByLabelText('Number'), '12')
  await user.type(within(form).getByLabelText('Text'), 'Test message')
  expect(within(form).getByText(NUMBER_RULE)).toBeInTheDocument()
  expect(within(form).getByRole('button', { name: 'Preview' })).toBeDisabled()
})

test('a live harness run keeps Read and disables delete and send', async () => {
  const user = userEvent.setup()
  renderSms(LIVE)
  await screen.findByText('3 of 20 on the SIM')
  const read = screen.getAllByRole('button', { name: 'Read' })[0]!
  expect(read).toBeEnabled()
  await user.click(read)
  expect(await screen.findByRole('region', { name: 'Message 1' })).toBeInTheDocument()
  await user.click(screen.getByRole('checkbox', { name: 'Select message 1' }))
  expect(await screen.findByRole('button', { name: 'Delete 1 message' })).toBeDisabled()
  const form = screen.getByRole('group', { name: 'Send SMS' })
  await user.type(within(form).getByLabelText('Number'), '+15550101')
  await user.type(within(form).getByLabelText('Text'), 'Test message')
  const preview = within(form).getByRole('button', { name: 'Preview' })
  expect(preview).toBeDisabled()
  expect(preview).toHaveAttribute('title', expect.stringContaining('Waits for the run: '))
  expect(screen.getByText(/A harness run is live .*: Delete and Send wait for it to end\./)).toBeInTheDocument()
  expect(posts).toHaveLength(0)
})
