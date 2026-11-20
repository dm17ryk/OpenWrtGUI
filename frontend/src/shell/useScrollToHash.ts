import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router'

/**
 * Scrolls once to the element the URL's `#hash` names (a Discovery chip links to a card such as
 * `/routers/ap1/rf#channel-analysis`; React Router does not scroll to hashes). The card may render after the
 * screen's first paint, so it looks again after each render until it finds it.
 */
export function useScrollToHash(): void {
  const { hash } = useLocation()
  const done = useRef<string | null>(null)
  useEffect(() => {
    if (hash.length < 2 || done.current === hash) return
    const el = document.getElementById(decodeURIComponent(hash.slice(1)))
    if (el) {
      el.scrollIntoView({ block: 'start' })
      done.current = hash
    }
  })
}
