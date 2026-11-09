import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, apiFetch } from '../../api/client'
import type { ProcessList, ProcessRow } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'

type Column = 'pid' | 'ppid' | 'user' | 'state' | 'mem_kib' | 'cpu_pct' | 'command'
// numbers sort largest first (what a person looks for), text A to Z
const NUMERIC: readonly Column[] = ['mem_kib', 'cpu_pct']

function compare(a: ProcessRow, b: ProcessRow, by: Column): number {
  const x = a[by]
  const y = b[by]
  if (typeof x === 'number' && typeof y === 'number') return NUMERIC.includes(by) ? y - x : x - y
  return String(x).localeCompare(String(y))
}

/** Every process `top -bn1` shows, read-only (D10), sorted by CPU until another heading is clicked. */
export function ProcessesTab({ routerId }: { routerId: string }) {
  const [by, setBy] = useState<Column>('cpu_pct')
  const list = useQuery({ queryKey: ['system-processes', routerId], queryFn: () => apiFetch<ProcessList>(`/api/routers/${routerId}/system/processes`) })
  const memory = list.data?.column ?? 'memory'
  const columns: ReadonlyArray<readonly [Column, string]> = [
    ['pid', 'PID'],
    ['ppid', 'Parent'],
    ['user', 'User'],
    ['state', 'State'],
    ['mem_kib', `${memory} (KiB)`],
    ['cpu_pct', 'CPU %'],
    ['command', 'Command'],
  ]
  const rows = [...(list.data?.rows ?? [])].sort((a, b) => compare(a, b, by))
  return (
    <section className="card stack" aria-labelledby="system-procs-h">
      <div className="row">
        <div className="hrow">
          <h2 id="system-procs-h">Processes</h2>
          <Help topic={HELP.systemProcesses} />
        </div>
        <div className="spacer" />
        {list.data?.cpu && <span className="muted mono">{list.data.cpu}</span>}
        <button type="button" className="btn" onClick={() => void list.refetch()}>
          Read again
        </button>
      </div>
      {list.error && <div className="note x">{list.error instanceof ApiError ? list.error.detail : list.error.message}</div>}
      {list.isPending && <div className="muted">Reading the processes…</div>}
      {list.data && (
        <div className="scroll-x">
          <table className="tbl" aria-label="Processes">
            <thead>
              <tr>
                {columns.map(([key, label]) => (
                  <th key={key} aria-sort={by === key ? (NUMERIC.includes(key) ? 'descending' : 'ascending') : undefined}>
                    <button type="button" className="th-sort" onClick={() => setBy(key)}>
                      {label}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.pid}>
                  <td className="mono">{p.pid}</td>
                  <td className="mono">{p.ppid}</td>
                  <td>{p.user}</td>
                  <td>{p.state}</td>
                  <td className="mono">{`${p.mem_kib} (${p.mem_pct}%)`}</td>
                  <td className="mono">{p.cpu_pct}</td>
                  <td className="mono">{p.command}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
