import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { apiFetch } from '../../api/client'
import type { RebootJob } from '../../api/types'

export const JOB_POLL_MS = 2000

/** A reboot, a restore or a reset still on its way (the router allows one job at a time). */
export const isRunning = (job: RebootJob | null | undefined): boolean => job != null && (job.phase === 'armed' || job.phase === 'waiting')

/** The router's job (reboot, restore or reset), read every 2 s while it runs; every card shares the one query. */
export function useJob(routerId: string) {
  return useQuery({
    queryKey: ['system-reboot', routerId],
    queryFn: () => apiFetch<RebootJob | null>(`/api/routers/${routerId}/system/reboot`),
    refetchInterval: (q) => (isRunning(q.state.data) ? JOB_POLL_MS : false),
  })
}

/**
 * What a job changed is read again when it ends: the overview (a fresh uptime) once the router is back, the
 * router list once it was reset. Called once per screen, not per card, so each read happens once.
 */
export function useJobEnd(routerId: string): void {
  const client = useQueryClient()
  const phase = useJob(routerId).data?.phase
  useEffect(() => {
    if (phase === 'back') void client.invalidateQueries({ queryKey: ['system', routerId] })
    if (phase === 'reset') {
      void client.invalidateQueries({ queryKey: ['routers'] })
      void client.invalidateQueries({ queryKey: ['router', routerId] })
    }
  }, [phase, routerId, client])
}

/** Starts a job from its card: the polling starts from the job the router armed. */
export function useStartJob(routerId: string): (job: RebootJob) => void {
  const client = useQueryClient()
  return (job) => client.setQueryData(['system-reboot', routerId], job)
}
