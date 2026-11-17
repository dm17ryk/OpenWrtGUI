/** One socket frame as JSON; null when it is not JSON, so a bad frame is dropped instead of throwing out of
 * `onmessage` (#77 minor 11). The server sends only JSON: a bad frame means a cut or garbled one. */
export function parseFrame<T>(data: string): T | null {
  try {
    return JSON.parse(data) as T
  } catch {
    return null
  }
}
