import type { ReactNode } from 'react'

type Props = { label: string; checked: boolean; onChange: (on: boolean) => void; disabled?: boolean; children?: ReactNode }

/** An on/off switch (the Settings look); `label` names it for screen readers, `children` is the visible text. */
export function Toggle({ label, checked, onChange, disabled = false, children }: Props) {
  return (
    <button className="tg" type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onChange(!checked)}>
      <span className={checked ? 'track on' : 'track'}>
        <span className="knob" />
      </span>
      {children}
    </button>
  )
}
