import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { HashRouter, Route, Routes } from 'react-router'
import { apiFetch, putJson } from './api/client'
import { useLive } from './api/live'
import type { GuardOut, Settings, UpdateOut } from './api/types'
import { AddRouter } from './screens/AddRouter'
import { AuditLog } from './screens/AuditLog'
import { Dashboard } from './screens/Dashboard'
import { RouterOverview } from './screens/RouterOverview'
import { SettingsScreen } from './screens/Settings'
import { Terminal } from './screens/Terminal'
import { LuciPage } from './screens/luci/LuciPage'
import { RfLive } from './screens/rf/RfLive'
import { WifiScreen } from './screens/wifi/WifiScreen'
import { GuardBanner } from './shell/GuardBanner'
import { Header } from './shell/Header'
import { applyTheme, prefersDark, resolveTheme } from './theme'

function useSystemDark(): boolean {
  const [dark, setDark] = useState(prefersDark)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (): void => setDark(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return dark
}

export function App() {
  useLive()
  const client = useQueryClient()
  const guard = useQuery({ queryKey: ['guard'], queryFn: () => apiFetch<GuardOut>('/api/guard') })
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => apiFetch<Settings>('/api/settings') })
  const update = useQuery({ queryKey: ['update'], queryFn: () => apiFetch<UpdateOut>('/api/update') })
  const systemDark = useSystemDark()
  const resolved = resolveTheme(settings.data?.theme ?? 'system', systemDark)

  useEffect(() => applyTheme(resolved), [resolved])

  const toggleTheme = async (): Promise<void> => {
    if (!settings.data) return
    const next: Settings = { ...settings.data, theme: resolved === 'dark' ? 'light' : 'dark' }
    client.setQueryData(['settings'], next)
    client.setQueryData(['settings'], await putJson<Settings>('/api/settings', next))
  }

  return (
    <HashRouter>
      <Header guard={guard.data} theme={resolved} onToggleTheme={() => void toggleTheme()} updateAvailable={update.data?.available ?? false} />
      <GuardBanner guard={guard.data} />
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/add" element={<AddRouter />} />
        <Route path="/routers/:id" element={<RouterOverview />} />
        <Route path="/routers/:id/wifi" element={<WifiScreen />} />
        <Route path="/routers/:id/rf" element={<RfLive />} />
        <Route path="/routers/:id/luci" element={<LuciPage />} />
        <Route path="/terminal/:id?" element={<Terminal />} />
        <Route path="/audit" element={<AuditLog />} />
        <Route path="/settings" element={<SettingsScreen />} />
      </Routes>
    </HashRouter>
  )
}
