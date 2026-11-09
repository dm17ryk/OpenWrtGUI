import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { AP2_LTE } from '../../testing/lte'
import { ModemCard } from './ModemCard'

const IMEI = '353000000000001'

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    postJson: vi.fn(async (path: string) => {
      if (path === '/api/routers/ap2/lte/imei') return { imei: IMEI }
      throw new Error(`unexpected ${path}`)
    }),
  }
})

test('shows the modem details; Reveal shows the IMEI and Hide masks it again', async () => {
  const user = userEvent.setup()
  render(<ModemCard routerId="ap2" modem={AP2_LTE.modem} opmode={AP2_LTE.opmode} />)
  const card = screen.getByRole('region', { name: 'Modem' })
  for (const text of ['BroadMobi', 'BM806C', 'M1.2.0_E1.0.3_A1.1.8', 'online', '17 (names not mapped yet)', '/dev/ttyUSB2']) {
    expect(card).toHaveTextContent(text)
  }
  expect(card).not.toHaveTextContent(IMEI)
  expect(card).toHaveTextContent('••••')
  await user.click(screen.getByRole('button', { name: 'Reveal' }))
  expect(await screen.findByText(IMEI)).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Hide' }))
  expect(screen.queryByText(IMEI)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Help: Modem' })).toBeInTheDocument()
})
