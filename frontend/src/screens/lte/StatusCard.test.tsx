import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { AP2_LTE } from '../../testing/lte'
import { StatusCard } from './StatusCard'

const NO_HANDLE = 'Session up but no packet-data handle: the modem carries no data. Use Recover.'

test('a session up without a packet-data handle says so', () => {
  render(<StatusCard state={{ ...AP2_LTE, data_handle: false, works: false }} sample={null} />)
  expect(screen.getByRole('region', { name: 'Status' })).toHaveTextContent(NO_HANDLE)
})

test.each([true, null])('a handle of %s says nothing about it', (handle) => {
  render(<StatusCard state={{ ...AP2_LTE, data_handle: handle }} sample={null} />)
  expect(screen.queryByText(NO_HANDLE)).not.toBeInTheDocument()
})
