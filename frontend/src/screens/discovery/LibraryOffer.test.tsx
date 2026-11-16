import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { LibraryOut } from '../../api/types'
import { MINI_PROFILE } from '../../testing/discovery'
import { libraryEntry, libraryFixture } from '../../testing/library'
import { LibraryOffer } from './LibraryOffer'

const BOARD = 'dlink,dwr-921-c3-uboot'
const REVISION = 'r35692-b8bffeefdf'
const calls: string[] = []
let library: LibraryOut = libraryFixture
let release: (() => void) | null = null
let downloadError: ApiError | null = null
let hold = false

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      calls.push(`GET ${path}`)
      if (path.startsWith('/api/images/library?')) return library
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string) => {
      calls.push(`POST ${path}`)
      if (hold) await new Promise<void>((resolve) => (release = resolve))
      if (downloadError) throw downloadError
      return MINI_PROFILE
    }),
  }
})

beforeEach(() => {
  calls.length = 0
  library = libraryFixture
  release = null
  downloadError = null
  hold = false
})

function renderOffer(props: { board?: string; revision?: string; disabled?: boolean; onImported?: () => void } = {}) {
  const user = userEvent.setup()
  const onImported = props.onImported ?? vi.fn()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <LibraryOffer
        board={props.board ?? BOARD}
        revision={props.revision ?? REVISION}
        disabled={props.disabled ?? false}
        onImported={onImported}
      />
    </QueryClientProvider>,
  )
  return { user, onImported }
}

test('says it is looking while the library is read', async () => {
  renderOffer()
  expect(screen.getByText('Looking in the image library…')).toBeVisible()
  expect(await screen.findByRole('button', { name: 'Download and import' })).toBeVisible()
})

test('offers the matching build', async () => {
  renderOffer()
  expect(
    await screen.findByText(
      'Image library: D-Link DWR-921 C3 (U-Boot), r35692-b8bffeefdf, 10.8 MB, release DWR_921-c3-uboot-qmifix3',
    ),
  ).toBeVisible()
  expect(screen.getByRole('button', { name: 'Download and import' })).toBeEnabled()
  expect(calls).toEqual([`GET /api/images/library?board=${encodeURIComponent(BOARD)}&revision=${REVISION}`])
})

test('downloads only after a click and tells the card to refresh', async () => {
  hold = true
  const { user, onImported } = renderOffer()
  await user.click(await screen.findByRole('button', { name: 'Download and import' }))
  expect(await screen.findByRole('button', { name: 'Downloading 10.8 MB…' })).toBeDisabled()
  expect(calls).toContain(`POST /api/images/library/${libraryEntry.sha256}`)
  expect(onImported).not.toHaveBeenCalled()
  release?.()
  await vi.waitFor(() => expect(onImported).toHaveBeenCalledTimes(1))
  expect(await screen.findByRole('button', { name: 'Download and import' })).toBeEnabled()
})

test('leaves the button off while the card is busy elsewhere', async () => {
  renderOffer({ disabled: true })
  expect(await screen.findByRole('button', { name: 'Download and import' })).toBeDisabled()
})

test('does not download on its own', async () => {
  renderOffer()
  await screen.findByRole('button', { name: 'Download and import' })
  expect(calls.some((c) => c.startsWith('POST'))).toBe(false)
})

test('says when the library has no build', async () => {
  library = { ...libraryFixture, entries: [] }
  renderOffer({ board: 'x,y', revision: 'r1' })
  expect(await screen.findByText('The image library has no build for x,y r1.')).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Download and import' })).not.toBeInTheDocument()
})

test('shows the library error', async () => {
  library = { entries: [], read_at: null, skipped: 0, error: 'The image library on GitHub could not be reached: offline.' }
  renderOffer()
  expect(await screen.findByText('The image library on GitHub could not be reached: offline.')).toBeVisible()
  expect(screen.queryByText(/has no build for/)).not.toBeInTheDocument()
})

test('counts other builds of the same revision', async () => {
  library = { ...libraryFixture, entries: [libraryEntry, { ...libraryEntry, sha256: 'b'.repeat(64) }] }
  renderOffer()
  expect(
    await screen.findByText(
      '1 other build of this revision is listed in Settings › Images; Check firmware tells whether the router runs the one you downloaded.',
    ),
  ).toBeVisible()
})

test('uses the plural for several other builds', async () => {
  const other = (c: string) => ({ ...libraryEntry, sha256: c.repeat(64) })
  library = { ...libraryFixture, entries: [libraryEntry, other('b'), other('c')] }
  renderOffer()
  expect(
    await screen.findByText(
      '2 other builds of this revision are listed in Settings › Images; Check firmware tells whether the router runs the one you downloaded.',
    ),
  ).toBeVisible()
})

test('says how many releases could not be read', async () => {
  library = { ...libraryFixture, skipped: 1 }
  renderOffer()
  expect(await screen.findByText('1 release could not be read')).toBeVisible()
})

test('shows the download error', async () => {
  downloadError = new ApiError(422, 'x.bin does not match its release’s profiles.json; nothing was imported.', null)
  const { user, onImported } = renderOffer()
  await user.click(await screen.findByRole('button', { name: 'Download and import' }))
  expect(await screen.findByText(/nothing was imported\./)).toBeVisible()
  expect(onImported).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: 'Download and import' })).toBeEnabled()
})
