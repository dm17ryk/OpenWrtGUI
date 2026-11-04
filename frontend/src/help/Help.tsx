import { cloneElement, useEffect, useId, useLayoutEffect, useRef, useState, type ReactElement, type ReactNode } from 'react'
import { helpFor, type HelpEntry } from './manual'

/** Long enough to cross from the control to the bubble and click "More in the manual". */
const CLOSE_DELAY_MS = 200
/** Buttons describe themselves only when the pointer rests on them, not while it passes by. */
const BUTTON_OPEN_DELAY_MS = 350
const EDGE_PX = 8

const CONTROLS = ['a', 'button', 'input', 'select', 'textarea']

function useBubble(openDelayMs: number) {
  const [open, setOpen] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  // While the pointer is over the control or its bubble, losing focus does not close it (clicking
  // the bubble's text takes the focus away).
  const hovered = useRef(false)
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
    enter: () => {
      hovered.current = true
      later(true, openDelayMs)
    },
    leave: () => {
      hovered.current = false
      later(false, CLOSE_DELAY_MS)
    },
    blur: () => {
      if (!hovered.current) later(false, CLOSE_DELAY_MS)
    },
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
      {entry.blocks.map((block, i) => (
        // oxlint-disable-next-line react/no-array-index-key -- fixed text from the manual, never reordered
        <span key={i}>{block}</span>
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
      onMouseEnter={bubble.enter}
      onMouseLeave={bubble.leave}
      onFocus={bubble.show}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) bubble.blur()
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

type TipTarget = ReactElement<{ 'aria-describedby'?: string; tabIndex?: number }>

/**
 * Wraps a control (or a badge) so that resting on it, or focusing it, shows the manual's text for
 * it. A badge or other plain element is made focusable, so keyboard users reach its help too.
 */
export function HelpTip({ topic, children }: { topic: string; children: TipTarget }) {
  const id = useId()
  const bubble = useBubble(BUTTON_OPEN_DELAY_MS)
  const entry = helpFor(topic)
  if (!entry) return children
  const plain = typeof children.type === 'string' && !CONTROLS.includes(children.type)
  return (
    <Wrapper bubble={bubble}>
      {cloneElement(children, {
        'aria-describedby': bubble.open ? id : undefined,
        ...(plain && children.props.tabIndex === undefined ? { tabIndex: 0 } : {}),
      })}
      {bubble.open && <Bubble id={id} entry={entry} />}
    </Wrapper>
  )
}
