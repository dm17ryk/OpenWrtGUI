type Props<T extends string | number> = {
  label: string
  values: readonly T[]
  picked: readonly T[]
  onChange: (next: T[]) => void
  text: (value: T) => string
  name: (value: T) => string
}

/** A row of tick buttons: the step-through's modes, channels and TX powers. */
export function TickRow<T extends string | number>({ label, values, picked, onChange, text, name }: Props<T>) {
  const toggle = (value: T): void => {
    onChange(picked.includes(value) ? picked.filter((x) => x !== value) : [...picked, value])
  }
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="eyebrow">{label}</div>
      <div className="chans">
        {values.map((value) => (
          <button
            key={String(value)}
            type="button"
            className={`chan${picked.includes(value) ? ' on' : ''}`}
            aria-pressed={picked.includes(value)}
            aria-label={name(value)}
            onClick={() => toggle(value)}
          >
            <strong>{text(value)}</strong>
          </button>
        ))}
      </div>
    </div>
  )
}
