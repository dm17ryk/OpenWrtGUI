/**
 * Where each capability on Discovery leads (spec 7.8 Phase 2, v1.2a R3): the screen or card that uses it. A
 * capability without a page here (Throughput and Traffic generator until 1.2b) leads nowhere.
 */
const PATHS: Readonly<Record<string, string>> = {
  Switch: 'ports',
  LTE: 'lte',
  Capture: 'faults#capture',
  netem: 'faults',
  Firewall: 'firewall',
  'Monitor mode': 'rf#frame-analysis',
  'Air survey': 'rf#channel-analysis',
  'Port statistics': 'tools/port-stats',
  Connections: 'tools/connections',
}

export function capabilityLink(routerId: string, name: string): string | null {
  const path = Object.hasOwn(PATHS, name) ? PATHS[name] : undefined
  return path === undefined ? null : `/routers/${routerId}/${path}`
}
