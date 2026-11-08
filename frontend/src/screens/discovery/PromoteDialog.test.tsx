import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { ToolCard } from '../../api/types'
import { PORTCTL_CARD } from '../../testing/discovery'
import { PromoteDialog } from './PromoteDialog'

const TOOLS = '/api/tools/dlink%2Cdwr-921-c3-uboot'
const USAGE = 'Usage: dwr921-portctl {port-status|port-enable|port-disable} {lan1|lan2|lan3|lan4|wan}'
const calls: Array<{ path: string; body?: unknown }> = []
let refuse: ApiError | null = null

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    postJson: vi.fn(async (path: string, body?: unknown) => {
      calls.push({ path, body })
      if (path === `${TOOLS}/prefill`) return PORTCTL_CARD
      throw new Error(`unexpected ${path}`)
    }),
    putJson: vi.fn(async (path: string, body: unknown) => {
      calls.push({ path, body })
      if (refuse) throw refuse
      if (path === TOOLS) return body
      throw new Error(`unexpected ${path}`)
    }),
  }
})

beforeEach(() => {
  calls.length = 0
  refuse = null
})

function renderPromote(onSaved = vi.fn()) {
  const user = userEvent.setup()
  render(
    <PromoteDialog board="dlink,dwr-921-c3-uboot" path="/usr/sbin/dwr921-portctl" usage={USAGE} onClose={vi.fn()} onSaved={onSaved} />,
  )
  return user
}

test('promotes with commands filled from the usage line', async () => {
  renderPromote()
  expect(await screen.findByDisplayValue('port-status')).toBeVisible()
  expect(screen.getByDisplayValue('port-enable')).toBeVisible()
  expect(screen.getByDisplayValue('port-disable')).toBeVisible()
  expect(screen.getAllByDisplayValue('lan1 lan2 lan3 lan4 wan')).toHaveLength(3)
  expect(calls[0]).toEqual({ path: `${TOOLS}/prefill`, body: { path: '/usr/sbin/dwr921-portctl', usage: USAGE } })
})

test('saves the card with the read-only switch per command', async () => {
  const onSaved = vi.fn()
  const user = renderPromote(onSaved)
  const status = (await screen.findByDisplayValue('port-status')).closest('fieldset') as HTMLElement
  await user.click(within(status).getByRole('checkbox', { name: 'Changes the router' }))
  await user.click(screen.getByRole('button', { name: 'Save card' }))
  const saved = calls.find((c) => c.path === TOOLS)?.body as ToolCard
  expect(saved.commands.map((c) => [c.label, c.write])).toEqual([
    ['port-status', false],
    ['port-enable', true],
    ['port-disable', true],
  ])
  expect(saved.commands[0].params[0].choices).toEqual(['lan1', 'lan2', 'lan3', 'lan4', 'wan'])
  expect(onSaved).toHaveBeenCalled()
})

test('shows why a card was refused', async () => {
  refuse = new ApiError(422, 'a;b is not a literal (letters, digits and . _ : = , / @ + -) or a {parameter}', null)
  const user = renderPromote()
  const enable = (await screen.findByDisplayValue('port-enable')).closest('fieldset') as HTMLElement
  const args = within(enable).getByLabelText('Arguments')
  await user.clear(args)
  await user.type(args, 'a;b')
  await user.click(screen.getByRole('button', { name: 'Save card' }))
  expect(await screen.findByText(/a;b is not a literal/)).toBeVisible()
})
