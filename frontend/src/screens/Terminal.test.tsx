import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { LineConsole } from './LineConsole'
import { reduceLines } from './lineConsoleState'

test('terminal line mode shows the refused reason', () => {
  const lines = reduceLines([], {
    type: 'refused',
    line: 'reboot',
    reason: 'Refused while dima_night.py started 21:04 (PID 18244): only read-only commands run during a harness run.',
  })
  render(<LineConsole lines={lines} reason="Refused while dima_night.py started 21:04 (PID 18244)" onRun={() => undefined} />)
  expect(screen.getByText('Read-only mode: a harness run is in progress.')).toBeInTheDocument()
  expect(screen.getByText(/only read-only commands run during a harness run/)).toBeInTheDocument()
})

test('output and exit lines accumulate', () => {
  let lines = reduceLines([], { type: 'output', data: 'Linux AP2\r\n' })
  lines = reduceLines(lines, { type: 'exit', status: 0 })
  expect(lines.map((l) => l.text)).toEqual(['Linux AP2', '[exit 0]'])
})

test('a typed line is sent and the field cleared', async () => {
  const onRun = vi.fn()
  render(<LineConsole lines={[]} reason={null} onRun={onRun} />)
  const user = userEvent.setup()
  const field = screen.getByLabelText('Command')
  await user.type(field, 'uname -a{enter}')
  expect(onRun).toHaveBeenCalledWith('uname -a')
  expect(field).toHaveValue('')
})
