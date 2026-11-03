import { NavLink } from 'react-router'
import type { GuardOut } from '../api/types'
import type { Resolved } from '../theme'
import { guardPillText } from './guardText'

const SCREENS: ReadonlyArray<readonly [string, string]> = [
  ['/', 'Dashboard'],
  ['/add', 'Add router'],
  ['/terminal', 'Terminal'],
  ['/audit', 'Audit log'],
  ['/settings', 'Settings'],
]

type Props = {
  guard: GuardOut | undefined
  theme: Resolved
  onToggleTheme: () => void
  updateAvailable: boolean
}

export function Header({ guard, theme, onToggleTheme, updateAvailable }: Props) {
  const live = guard?.live ?? false
  return (
    <header className="top">
      <div className="brand">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#7FD1A8" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <path d="M5 12.5a10 10 0 0 1 14 0" />
          <path d="M8 15.5a6 6 0 0 1 8 0" />
          <circle cx="12" cy="19" r="1.4" fill="#7FD1A8" />
        </svg>
        <span>OpenWrt Bench</span>
      </div>
      <nav className="nav" aria-label="Screens">
        {SCREENS.map(([to, label]) => (
          <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'active' : '')}>
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="spacer" />
      {updateAvailable && (
        <NavLink to="/settings" className="pill update">
          Update available
        </NavLink>
      )}
      <span className={live ? 'pill live' : 'pill'}>
        <span className="dot" style={{ background: live ? '#B7A6F2' : '#6CD39B' }} />
        {guardPillText(guard)}
      </span>
      <button className="theme" type="button" aria-pressed={theme === 'dark'} onClick={onToggleTheme}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </svg>
        {theme === 'dark' ? 'Dark' : 'Light'}
      </button>
    </header>
  )
}
