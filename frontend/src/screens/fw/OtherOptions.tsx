type Props = { rows: Array<[string, string]>; onChange: (rows: Array<[string, string]>) => void }

/** A section's remaining uci options by name: edit a value, remove one, add one. */
export function OtherOptions({ rows, onChange }: Props) {
  const set = (i: number, at: 0 | 1, value: string): void => onChange(rows.map((r, j) => (j === i ? (at === 0 ? [value, r[1]] : [r[0], value]) : r)))
  return (
    <div className="stack" style={{ gap: 6 }}>
      <span className="muted">Other options</span>
      {rows.map(([k, v], i) => (
        <div key={i} className="row">
          <input className="in mono" aria-label={`Option ${i + 1} name`} value={k} onChange={(e) => set(i, 0, e.target.value)} />
          <input className="in mono" aria-label={`Option ${i + 1} value`} value={v} onChange={(e) => set(i, 1, e.target.value)} />
          <button className="btn" type="button" onClick={() => onChange(rows.filter((_, j) => j !== i))}>
            Remove
          </button>
        </div>
      ))}
      <div>
        <button className="btn" type="button" onClick={() => onChange([...rows, ['', '']])}>
          + Option
        </button>
      </div>
    </div>
  )
}
