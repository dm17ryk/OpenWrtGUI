const TOKEN_KEY = 'owg-token'

/** Error from the local API, with the server's own `detail` text (shown to the user as is). */
export class ApiError extends Error {
  readonly status: number
  readonly detail: string
  readonly body: unknown

  constructor(status: number, detail: string, body: unknown) {
    super(detail)
    this.status = status
    this.detail = detail
    this.body = body
  }
}

/**
 * The launcher opens `http://127.0.0.1:<port>/#token=<token>`. Keep the token for this
 * window only and remove it from the address bar.
 */
export function readTokenFromHash(loc: Location, storage: Storage): string | null {
  const match = /(?:^#|&)token=([^&]+)/.exec(loc.hash)
  if (match) {
    const token = decodeURIComponent(match[1])
    storage.setItem(TOKEN_KEY, token)
    history.replaceState(null, '', loc.pathname + loc.search + '#/')
    return token
  }
  return storage.getItem(TOKEN_KEY)
}

let token: string | null = null

export function setToken(value: string | null): void {
  token = value
}

export function getToken(): string | null {
  return token
}

function detailOf(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length > 0) return 'Some values are not valid.'
  }
  return fallback
}

export const LOST_CONNECTION = 'Lost the connection to OpenWrtGUI. The app may have closed. Start it again.'

/**
 * fetch(), except that "no answer at all" (the app closed, so its local server is gone)
 * becomes an ApiError with status 0 instead of the browser's "Failed to fetch".
 */
async function send(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(path, init)
  } catch (err) {
    if (err instanceof TypeError) throw new ApiError(0, LOST_CONNECTION, null)
    throw err
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body !== undefined && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const res = await send(path, { ...init, headers })
  const text = await res.text()
  let body: unknown = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = text
    }
  }
  if (!res.ok) throw new ApiError(res.status, detailOf(body, `${res.status} ${res.statusText}`), body)
  return body as T
}

export function postJson<T>(path: string, data?: unknown): Promise<T> {
  return apiFetch<T>(path, { method: 'POST', body: data === undefined ? undefined : JSON.stringify(data) })
}

export function putJson<T>(path: string, data: unknown): Promise<T> {
  return apiFetch<T>(path, { method: 'PUT', body: JSON.stringify(data) })
}

/** A file as the raw request body (an imported firmware image); its name travels in X-File-Name. */
export function postBytes<T>(path: string, data: ArrayBuffer, name: string): Promise<T> {
  return apiFetch<T>(path, {
    method: 'POST',
    body: data,
    headers: { 'Content-Type': 'application/octet-stream', 'X-File-Name': name },
  })
}

export function socketUrl(path: string, params: Record<string, string> = {}): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const query = new URLSearchParams({ ...params, t: token ?? '' })
  return `${proto}//${location.host}${path}?${query.toString()}`
}

export function openSocket(path: string, params: Record<string, string> = {}): WebSocket {
  return new WebSocket(socketUrl(path, params))
}

/** Download a protected file (the token travels in a header, so a plain link cannot do it). */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const res = await send(path, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
  if (!res.ok) throw new ApiError(res.status, `${res.status} ${res.statusText}`, null)
  const name = /filename="?([^"]+)"?/.exec(res.headers.get('content-disposition') ?? '')?.[1] ?? fallbackName
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}
