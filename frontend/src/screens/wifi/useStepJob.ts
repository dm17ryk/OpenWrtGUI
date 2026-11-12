import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '../../api/client'
import type { PendingRestore, StepJob } from '../../api/types'

const STEP_POLL_MS = 1000
const ENDED: ReadonlyArray<StepJob['phase']> = ['done', 'stopped', 'failed']
export const WAITING: ReadonlyArray<StepJob['phase']> = ['dwell', 'waiting for station', 'waiting for Next']

export function isRunning(job: StepJob | null | undefined): boolean {
  return !!job && !ENDED.includes(job.phase)
}

/** The router's step-through, polled every second while it runs (plan D5: dwells and re-joins count down). */
export function useStepJob(routerId: string) {
  return useQuery({
    queryKey: ['step-through', routerId],
    queryFn: () => apiFetch<StepJob | null>(`/api/routers/${routerId}/wifi/step-through`),
    refetchInterval: (q) => (isRunning(q.state.data) ? STEP_POLL_MS : false),
  })
}

/** Restores a step-through left behind (plan D6): the app ended before it put the radio back. */
export function usePendingRestores() {
  return useQuery({ queryKey: ['step-pending'], queryFn: () => apiFetch<PendingRestore[]>('/api/step-through/pending') })
}
