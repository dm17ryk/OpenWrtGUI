import { render, screen, within } from '@testing-library/react'
import { expect, test } from 'vitest'
import type { RateRow } from '../../api/types'
import { RatesTable } from './RatesTable'

const ROWS: RateRow[] = [
  { rate: 'MCS14', mode: 'HT20 LGI', attempts: 300, success_pct: 90, in_use: false },
  { rate: 'MCS15', mode: 'HT20 LGI', attempts: 900, success_pct: 94.44, in_use: true },
  { rate: 'MCS12', mode: 'HT20 SGI', attempts: 200, success_pct: 98, in_use: false },
]

test('rows show the rate, mode, attempts, success and the one in use', () => {
  render(<RatesTable rows={ROWS} error={undefined} />)
  const rows = within(screen.getByRole('table', { name: 'Rates' })).getAllByRole('row').slice(1)
  expect(rows).toHaveLength(3)
  const inUse = rows[1]
  for (const text of ['MCS15', 'HT20 LGI', '900', '94 %', 'in use']) expect(inUse).toHaveTextContent(text)
  expect(screen.getAllByText('in use')).toHaveLength(1)
})

test('no rows and an error each say so', () => {
  const { rerender } = render(<RatesTable rows={[]} error={undefined} />)
  expect(screen.getByText('No rate statistics for this station yet.')).toBeInTheDocument()
  rerender(<RatesTable rows={undefined} error="The radio is off: no station to read rates for" />)
  expect(screen.getByText('The radio is off: no station to read rates for')).toBeInTheDocument()
})
