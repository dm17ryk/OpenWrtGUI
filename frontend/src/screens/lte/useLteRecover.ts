import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '../../api/client'
import type { LteRecoverJob } from '../../api/types'

const RECOVER_POLL_MS = 2000

export function isRecovering(job: LteRecoverJob | null | undefined): boolean {
  return job?.phase === 'running'
}

/** The router's Recover job (spec 4.2), polled every 2 s while it runs, as the step-through's is. */
export function useLteRecover(routerId: string) {
  return useQuery({
    queryKey: ['lte-recover', routerId],
    queryFn: () => apiFetch<LteRecoverJob | null>(`/api/routers/${routerId}/lte/recover`),
    refetchInterval: (q) => (isRecovering(q.state.data) ? RECOVER_POLL_MS : false),
  })
}
