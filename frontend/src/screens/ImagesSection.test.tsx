import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { ProfileOut } from '../api/types'
import { MINI_PROFILE } from '../testing/discovery'
import { ImagesSection, ImportImage } from './ImagesSection'

const calls: Array<{ path: string; init?: RequestInit; name?: string }> = []
let images: ProfileOut[] = []
let importError: ApiError | null = null

vi.mock('../api/client', async (orig) => {
  const actual = await orig<typeof import('../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string, init?: RequestInit) => {
      calls.push({ path, init })
      if (path === '/api/images') return images
      if (init?.method === 'DELETE') return null
      throw new Error(`unexpected ${path}`)
    }),
    postBytes: vi.fn(async (path: string, _data: ArrayBuffer, name: string) => {
      calls.push({ path, name })
      if (importError) throw importError
      images = [MINI_PROFILE]
      return MINI_PROFILE
    }),
  }
})

beforeEach(() => {
  calls.length = 0
  images = []
  importError = null
})

function renderImages(client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={client}>
      <ImagesSection />
    </QueryClientProvider>,
  )
  return user
}

test('imports an image and lists it', async () => {
  const user = renderImages()
  expect(await screen.findByText(/No image imported yet/)).toBeVisible()
  await user.upload(screen.getByLabelText('Import image…'), new File([new Uint8Array(8)], 'mini-r35692.bin'))
  expect(await screen.findByText('dlink,dwr-921-c3-uboot r35692-b8bffeefdf')).toBeVisible()
  expect(screen.getByText(/custom: dwr921-diag, dwr921-internet-led, dwr921-portctl/)).toBeVisible()
  expect(calls.find((c) => c.name)).toEqual({ path: '/api/images', name: 'mini-r35692.bin' })
})

test('links an image from the library to its release, named (0.8.2 ledger, Task 7)', async () => {
  images = [{ ...MINI_PROFILE, origin: 'https://github.com/dm17ryk/openwrt/releases/tag/v25.12.5' }]
  renderImages()
  expect(await screen.findByRole('link', { name: 'from the image library (v25.12.5)' })).toHaveAttribute(
    'href',
    'https://github.com/dm17ryk/openwrt/releases/tag/v25.12.5',
  )
})

test('an origin without a release tag keeps the plain link text', async () => {
  images = [{ ...MINI_PROFILE, origin: 'https://github.com/dm17ryk/openwrt/releases' }]
  renderImages()
  expect(await screen.findByRole('link', { name: 'from the image library' })).toBeVisible()
})

test('Import image… looks disabled while it is off (0.8.2 final review)', async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ImportImage onImported={() => {}} disabled />
    </QueryClientProvider>,
  )
  const label = screen.getByText('Import image…').closest('label') as HTMLElement
  expect(label).toHaveAttribute('aria-disabled', 'true')
  expect(label).toHaveClass('disabled')
})

test('shows no library link for a hand-imported image', async () => {
  images = [MINI_PROFILE]
  renderImages()
  await screen.findByText(MINI_PROFILE.label)
  expect(screen.queryByRole('link', { name: 'from the image library' })).not.toBeInTheDocument()
})

test('shows why an import was refused', async () => {
  importError = new ApiError(422, 'No squashfs root file system in x.bin', null)
  const user = renderImages()
  await user.upload(screen.getByLabelText('Import image…'), new File([new Uint8Array(8)], 'x.bin'))
  expect(await screen.findByText('No squashfs root file system in x.bin')).toBeVisible()
})

test('deletes an image after confirming', async () => {
  images = [MINI_PROFILE]
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  const user = renderImages()
  await user.click(await screen.findByRole('button', { name: 'Delete' }))
  const deleted = calls.find((c) => c.init?.method === 'DELETE')
  expect(deleted?.path).toBe(`/api/images/dlink%2Cdwr-921-c3-uboot/${MINI_PROFILE.folder}`)
})

function libraryClient(): QueryClient {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['library', 'all'], { entries: [], read_at: null, skipped: 0, error: null })
  return client
}

test('deleting an image marks the image library out of date', async () => {
  images = [MINI_PROFILE]
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  const client = libraryClient()
  const user = renderImages(client)
  await user.click(await screen.findByRole('button', { name: 'Delete' }))
  await vi.waitFor(() => expect(client.getQueryState(['library', 'all'])?.isInvalidated).toBe(true))
})

test('importing an image marks the image library out of date', async () => {
  const client = libraryClient()
  const user = renderImages(client)
  await screen.findByText(/No image imported yet/)
  await user.upload(screen.getByLabelText('Import image…'), new File([new Uint8Array(8)], 'mini-r35692.bin'))
  await screen.findByText(MINI_PROFILE.label)
  await vi.waitFor(() => expect(client.getQueryState(['library', 'all'])?.isInvalidated).toBe(true))
})
