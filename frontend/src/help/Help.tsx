import { cloneElement, useEffect, useId, useLayoutEffect, useRef, useState, type ReactElement, type ReactNode } from 'react'
import { helpFor, type HelpEntry } from './manual'

/** Long enough to cross from the control to the bubble and click "More in the manual". */
const CLOSE_DELAY_MS = 200
/** Buttons describe themselves only when the pointer rests on them, not while it passes by. */
const BUTTON_OPEN_DELAY_MS = 350
const EDGE_PX = 8

function useBubble(openDelayMs: number) {
  const [open, setOpen] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  const later = (value: boolean, ms: number): void => {
    window.clearTimeout(timer.current)
    if (ms === 0) setOpen(value)
    else timer.current = window.setTimeout(() => setOpen(value), ms)
  }
  useEffect(() => () => window.clearTimeout(timer.current), [])
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e: KeyboardEvent): void => {
      if (e.key !== 'Escape') return
      window.clearTimeout(timer.current)
      setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])
  return {
    open,
    show: () => later(true, 0),
    hoverShow: () => later(true, openDelayMs),
    hide: () => later(false, CLOSE_DELAY_MS),
  }
}

function Bubble({ id, entry }: { id: string; entry: HelpEntry }) {
  const ref = useRef<HTMLSpanElement>(null)
  const [shift, setShift] = useState(0)
  // Keep the bubble inside the window at 375 px: slide it left or right if it would stick out.
  useLayoutEffect(() => {
    const rect = ref.current?.getBoundingClientRect()
    if (!rect) return
    if (rect.right > window.innerWidth - EDGE_PX) setShift(window.innerWidth - EDGE_PX - rect.right)
    else if (rect.left < EDGE_PX) setShift(EDGE_PX - rect.left)
  }, [])
  return (
    <span ref={ref} role="tooltip" id={id} className="help-tip" style={shift ? { transform: `translateX(${shift}px)` } : undefined}>
      <strong>{entry.title}</strong>
      {entry.blocks.map((block) => (
        <span key={block}>{block}</span>
      ))}
      <a href={entry.url} target="_blank" rel="noopener noreferrer">
        More in the manual
      </a>
    </span>
  )
}

function Wrapper({ bubble, children }: { bubble: ReturnType<typeof useBubble>; children: ReactNode }) {
  return (
    <span
      className="help"
      onMouseEnter={bubble.hoverShow}
      onMouseLeave={bubble.hide}
      onFocus={bubble.show}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) bubble.hide()
      }}
    >
      {children}
    </span>
  )
}

/** A small "?" button next to a page title or section heading; the manual's text for it on hover or focus. */
export function Help({ topic }: { topic: string }) {
  const id = useId()
  const bubble = useBubble(0)
  const entry = helpFor(topic)
  if (!entry) return null
  return (
    <Wrapper bubble={bubble}>
      <button
        type="button"
        className="help-btn"
        aria-label={`Help: ${entry.title}`}
        aria-describedby={bubble.open ? id : undefined}
        data-open={bubble.open || undefined}
        onClick={bubble.show}
      >
        <span aria-hidden="true">?</span>
      </button>
      {bubble.open && <Bubble id={id} entry={entry} />}
    </Wrapper>
  )
}

/** Wraps a button or link so that resting on it, or focusing it, shows the manual's text for it. */
export function HelpTip({ topic, children }: { topic: string; children: ReactElement<{ 'aria-describedby'?: string }> }) {
  const id = useId()
  const bubble = useBubble(BUTTON_OPEN_DELAY_MS)
  const entry = helpFor(topic)
  if (!entry) return children
  return (
    <Wrapper bubble={bubble}>
      {cloneElement(children, { 'aria-describedby': bubble.open ? id : undefined })}
      {bubble.open && <Bubble id={id} entry={entry} />}
    </Wrapper>
  )
}
