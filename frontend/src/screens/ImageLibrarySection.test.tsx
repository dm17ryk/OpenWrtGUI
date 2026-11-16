import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { LibraryOut } from '../api/types'
import { MINI_PROFILE } from '../testing/discovery'
import { libraryEntry, libraryFixture } from '../testing/library'
import { ImageLibrarySection } from './ImageLibrarySection'

const calls: string[] = []
let library: LibraryOut = libraryFixture
let refreshed: LibraryOut = libraryFixture
let release: (() => void) | null = null
let hold = false
let downloadError: ApiError | null = null

vi.mock('../api/client', async (orig) => {
  const actual = await orig<typeof import('../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      calls.push(`GET ${path}`)
      if (path === '/api/images/library') return library
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string) => {
      calls.push(`POST ${path}`)
      if (path === '/api/images/library/refresh') {
        library = refreshed
        return refreshed
      }
      if (hold) await new Promise<void>((resolve) => (release = resolve))
      if (downloadError) throw downloadError
      library = { ...library, entries: library.entries.map((e) => ({ ...e, imported: true })) }
      return MINI_PROFILE
    }),
  }
})

beforeEach(() => {
  calls.length = 0
  library = libraryFixture
  refreshed = libraryFixture
  release = null
  hold = false
  downloadError = null
})

function renderSection() {
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ImageLibrarySection />
    </QueryClientProvider>,
  )
  return user
}

test('lists every library image with its state', async () => {
  library = {
    ...libraryFixture,
    entries: [
      libraryEntry,
      { ...libraryEntry, sha256: 'b'.repeat(64), release_name: 'beta', release_url: 'https://x/beta', prerelease: true, imported: true },
    ],
  }
  renderSection()
  const rows = await screen.findAllByRole('listitem')
  expect(rows).toHaveLength(2)
  expect(within(rows[0]).getByText('D-Link DWR-921 C3 (U-Boot)')).toBeVisible()
  expect(within(rows[0]).getByText(/dlink,dwr-921-c3-uboot/)).toBeVisible()
  expect(within(rows[0]).getByText(/r35692-b8bffeefdf/)).toBeVisible()
  expect(within(rows[0]).getByRole('link', { name: 'DWR_921-c3-uboot-qmifix3' })).toHaveAttribute('href', libraryEntry.release_url)
  expect(within(rows[0]).getByText(/10\.8 MB/)).toBeVisible()
  expect(within(rows[0]).queryByText(/pre-release/)).not.toBeInTheDocument()
  expect(within(rows[0]).getByRole('button', { name: 'Download' })).toBeEnabled()
  expect(within(rows[1]).getByRole('link', { name: 'beta' })).toHaveAttribute('href', 'https://x/beta')
  expect(within(rows[1]).getByText(/pre-release/)).toBeVisible()
  expect(within(rows[1]).getByText('Imported')).toBeVisible()
  expect(within(rows[1]).queryByRole('button', { name: 'Download' })).not.toBeInTheDocument()
})

test('downloads one image', async () => {
  hold = true
  const user = renderSection()
  await user.click(await screen.findByRole('button', { name: 'Download' }))
  expect(await screen.findByRole('button', { name: 'Downloading…' })).toBeDisabled()
  expect(calls).toContain(`POST /api/images/library/${libraryEntry.sha256}`)
  release?.()
  expect(await screen.findByText('Imported')).toBeVisible()
})

test('does not download on its own', async () => {
  renderSection()
  await screen.findByRole('button', { name: 'Download' })
  expect(calls.some((c) => c.startsWith('POST'))).toBe(false)
})

test('shows why a download was refused', async () => {
  downloadError = new ApiError(422, 'x.bin does not match its release’s profiles.json; nothing was imported.', null)
  const user = renderSection()
  await user.click(await screen.findByRole('button', { name: 'Download' }))
  expect(await screen.findByText(/nothing was imported\./)).toBeVisible()
  expect(screen.getByRole('button', { name: 'Download' })).toBeEnabled()
})

test('refreshes on demand and shows the read time', async () => {
  refreshed = { ...libraryFixture, read_at: '2026-11-16T10:35:00', entries: [] }
  const user = renderSection()
  expect(await screen.findByText('Read at 09:00')).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Refresh' }))
  expect(await screen.findByText('Read at 10:35')).toBeVisible()
  expect(calls).toContain('POST /api/images/library/refresh')
  expect(screen.queryByRole('button', { name: 'Download' })).not.toBeInTheDocument()
})

test('shows the skipped count', async () => {
  library = { ...libraryFixture, skipped: 1 }
  renderSection()
  expect(await screen.findByText('1 release could not be read')).toBeVisible()
})

test('uses the plural for several skipped releases', async () => {
  library = { ...libraryFixture, skipped: 3 }
  renderSection()
  expect(await screen.findByText('3 releases could not be read')).toBeVisible()
})

test('shows the library error', async () => {
  library = { entries: [], read_at: null, skipped: 0, error: 'The image library on GitHub could not be reached: offline.' }
  renderSection()
  expect(await screen.findByText('The image library on GitHub could not be reached: offline.')).toBeVisible()
  expect(screen.queryByText(/^Read at/)).not.toBeInTheDocument()
})
