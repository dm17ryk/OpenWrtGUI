import type { TerminalMessage } from '../api/types'

export type ConsoleLine = { id: number; text: string; kind: 'out' | 'cmd' | 'refused' | 'exit' | 'error' }

const MAX_LINES = 500
let nextId = 0

/** Fold one terminal message into the line-mode transcript. */
export function reduceLines(lines: ConsoleLine[], msg: TerminalMessage): ConsoleLine[] {
  const add = (text: string, kind: ConsoleLine['kind']): ConsoleLine => ({ id: nextId++, text, kind })
  let extra: ConsoleLine[] = []
  if (msg.type === 'output') {
    extra = msg.data
      .replace(/\r\n/g, '\n')
      .replace(/\n$/, '')
      .split('\n')
      .map((t) => add(t, 'out'))
  } else if (msg.type === 'refused') {
    extra = [add(`$ ${msg.line}`, 'cmd'), add(msg.reason, 'refused')]
  } else if (msg.type === 'exit') {
    extra = [add(`[exit ${msg.status}]`, 'exit')]
  } else if (msg.type === 'error') {
    extra = [add(msg.detail, 'error')]
  }
  return [...lines, ...extra].slice(-MAX_LINES)
}

export function commandLine(lines: ConsoleLine[], text: string): ConsoleLine[] {
  return [...lines, { id: nextId++, text: `$ ${text}`, kind: 'cmd' as const }].slice(-MAX_LINES)
}
