import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { ScreenBoundary } from './ScreenBoundary'

let throws = true

function Thrower({ message }: { message: string }) {
  if (throws) throw new Error(message)
  return <p>the screen</p>
}

beforeEach(() => {
  throws = true
  vi.spyOn(console, 'error').mockImplementation(() => {}) // React reports the caught error
})

afterEach(() => {
  vi.restoreAllMocks()
})

test('a screen that throws shows its error and keeps the rest', () => {
  render(
    <>
      <nav>rail</nav>
      <ScreenBoundary>
        <Thrower message="bad data" />
      </ScreenBoundary>
    </>,
  )
  expect(screen.getByText('This screen hit an error: bad data. The other screens still work.')).toBeInTheDocument()
  expect(screen.getByText('rail')).toBeInTheDocument()
})

test('Try again renders the screen again', async () => {
  const user = userEvent.setup()
  render(
    <ScreenBoundary>
      <Thrower message="once" />
    </ScreenBoundary>,
  )
  throws = false
  await user.click(screen.getByRole('button', { name: 'Try again' }))
  expect(screen.getByText('the screen')).toBeInTheDocument()
})

test('another screen starts clean', () => {
  const { rerender } = render(
    <ScreenBoundary key="/routers/ap1/lte">
      <Thrower message="bad data" />
    </ScreenBoundary>,
  )
  throws = false
  rerender(
    <ScreenBoundary key="/routers/ap1/wifi">
      <Thrower message="unused" />
    </ScreenBoundary>,
  )
  expect(screen.getByText('the screen')).toBeInTheDocument()
})
