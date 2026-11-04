import { afterEach, describe, expect, test, vi } from 'vitest'
import { ApiError, apiFetch, downloadFile, readTokenFromHash, setToken } from './client'

const LOST = 'Lost the connection to OpenWrtGUI. The app may have closed. Start it again.'

function serverGone() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }),
  )
}

describe('readTokenFromHash', () => {
  test('token moves from hash to sessionStorage and the hash is cleared', () => {
    history.replaceState(null, '', '/#token=abc%2D1')
    expect(readTokenFromHash(window.location, sessionStorage)).toBe('abc-1')
    expect(sessionStorage.getItem('owg-token')).toBe('abc-1')
    expect(window.location.hash).toBe('#/')
  })

  test('falls back to the stored token after a reload', () => {
    sessionStorage.setItem('owg-token', 'kept')
    history.replaceState(null, '', '/#/settings')
    expect(readTokenFromHash(window.location, sessionStorage)).toBe('kept')
    expect(window.location.hash).toBe('#/settings')
  })
})

describe('apiFetch', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  test('sends the bearer token and returns JSON', async () => {
    const fetchMock = vi.fn(async () => new Response('{"ok":true}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    setToken('t1')
    expect(await apiFetch('/api/x')).toEqual({ ok: true })
    const init = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(new Headers(init[1].headers).get('Authorization')).toBe('Bearer t1')
  })

  test('throws ApiError with the server detail', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"detail":"The router refused the login."}', { status: 403 })))
    await expect(apiFetch('/api/x')).rejects.toEqual(expect.objectContaining({ status: 403, detail: 'The router refused the login.' }))
    await expect(apiFetch('/api/x')).rejects.toBeInstanceOf(ApiError)
  })

  test('a closed app reads as a lost connection, not "Failed to fetch"', async () => {
    serverGone()
    await expect(apiFetch('/api/x')).rejects.toEqual(expect.objectContaining({ status: 0, detail: LOST }))
    await expect(apiFetch('/api/x')).rejects.toBeInstanceOf(ApiError)
  })

  test('an aborted request is passed through unchanged', async () => {
    const abort = new DOMException('The operation was aborted.', 'AbortError')
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw abort
      }),
    )
    await expect(apiFetch('/api/x')).rejects.toBe(abort)
  })
})

describe('downloadFile', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  test('a closed app reads as a lost connection', async () => {
    serverGone()
    await expect(downloadFile('/api/audit/export', 'audit.zip')).rejects.toEqual(
      expect.objectContaining({ status: 0, detail: LOST }),
    )
  })
})
