import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import type { ApplyResult, Check } from '../api/types'
import { CheckList } from './CheckList'

const OK: Check[] = [
  { name: 'radio', ok: true, detail: 'up on phy0-ap0' },
  { name: 'channel', ok: true, detail: 'channel 6' },
  { name: 'beacon rate', ok: true, detail: '6.0 Mb/s ×5' },
]

function result(extra: Partial<ApplyResult>): ApplyResult {
  return { router_id: 'ap2', radio: 'radio0', applied: true, verified: true, checks: OK, error: null, ...extra }
}

test('proven on air lists every check', () => {
  render(<CheckList result={result({})} />)
  const status = screen.getByRole('status', { name: 'Apply result' })
  expect(status).toHaveTextContent('Applied and proven on air')
  expect(status).toHaveTextContent('beacon rate')
  expect(status).toHaveTextContent('6.0 Mb/s ×5')
})

test('applied but a check failed is not shown as done', () => {
  const checks: Check[] = [...OK.slice(0, 2), { name: 'beacon rate', ok: false, detail: 'no beacon seen in 5 s' }]
  render(<CheckList result={result({ verified: false, checks })} />)
  expect(screen.getByRole('status')).toHaveTextContent('Applied, not verified: beacon rate')
  expect(screen.getByRole('status')).toHaveTextContent('no beacon seen in 5 s')
})

test('a lost connection after the commit names the reason', () => {
  render(<CheckList result={result({ verified: false, checks: [], error: 'Lost the connection to AP2 after the change was committed' })} />)
  expect(screen.getByRole('status')).toHaveTextContent('Applied, not verified: Lost the connection to AP2')
})

test('not applied', () => {
  render(<CheckList result={result({ applied: false, verified: false, checks: [], error: 'The router refused the change: busy' })} />)
  expect(screen.getByRole('status')).toHaveTextContent('Not applied: The router refused the change: busy')
})
