import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { expect, test } from 'vitest'
import type { GuardOut } from '../api/types'
import { GuardBanner } from './GuardBanner'
import { guardPillText } from './guardText'
import { Header } from './Header'

const clear: GuardOut = { live: false, reasons: [], checked_at: '2026-11-03T21:00:00' }
const live: GuardOut = {
  live: true,
  checked_at: '2026-11-03T21:05:00',
  reasons: [
    {
      kind: 'process',
      detail: 'dima_night.py',
      since: '2026-11-03T21:04:00',
      router: null,
      pid: 18244,
      text: 'dima_night.py started 21:04 (PID 18244)',
    },
  ],
}

test('guard pill text', () => {
  expect(guardPillText(clear)).toBe('No harness running · writes allowed')
  expect(guardPillText(live)).toBe('dima_night.py running · read-only')
  expect(guardPillText(undefined)).toBe('Checking Bench Guard…')
})

test('header shows the pill and the screens', () => {
  render(
    <MemoryRouter>
      <Header guard={live} theme="light" onToggleTheme={() => undefined} updateAvailable />
    </MemoryRouter>,
  )
  expect(screen.getByText('dima_night.py running · read-only')).toBeInTheDocument()
  for (const name of ['Dashboard', 'Add router', 'Terminal', 'Audit log', 'Settings']) {
    expect(screen.getByRole('link', { name: new RegExp(name) })).toBeInTheDocument()
  }
  expect(screen.getByText('Update available')).toBeInTheDocument()
})

test('banner names the run and only shows while live', () => {
  const { container, rerender } = render(<GuardBanner guard={clear} />)
  expect(container).toBeEmptyDOMElement()
  rerender(<GuardBanner guard={live} />)
  expect(screen.getByRole('status')).toHaveTextContent(
    'Bench Guard: every router is read-only. dima_night.py started 21:04 (PID 18244). Status, stations and read-only commands still work. Writes come back when it ends.',
  )
  expect(screen.getByRole('button', { name: 'Help: What still works during a run' })).toBeInTheDocument()
})
