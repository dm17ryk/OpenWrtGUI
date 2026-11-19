import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, test, vi } from 'vitest'
import { useScrollToHash } from './useScrollToHash'

function Page({ isReady }: { isReady: boolean }) {
  useScrollToHash()
  return isReady ? <section id="channel-analysis">Channel analysis</section> : <p>Reading…</p>
}

const scroll = vi.fn()

afterEach(() => {
  scroll.mockReset()
})

function show(isReady: boolean, entry = '/routers/ap1/rf#channel-analysis') {
  Element.prototype.scrollIntoView = scroll
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Page isReady={isReady} />
    </MemoryRouter>,
  )
}

test('scrolls to the card named in the hash once it is there', () => {
  const view = show(false)
  expect(scroll).not.toHaveBeenCalled()
  view.rerender(
    <MemoryRouter initialEntries={['/routers/ap1/rf#channel-analysis']}>
      <Page isReady />
    </MemoryRouter>,
  )
  expect(scroll).toHaveBeenCalledTimes(1)
  view.rerender(
    <MemoryRouter initialEntries={['/routers/ap1/rf#channel-analysis']}>
      <Page isReady />
    </MemoryRouter>,
  )
  expect(scroll).toHaveBeenCalledTimes(1) // once: a later refresh does not pull the page back
})

test('no hash, no scroll', () => {
  show(true, '/routers/ap1/rf')
  expect(scroll).not.toHaveBeenCalled()
})
