/**
 * Where each capability on Discovery leads (spec 7.8 Phase 2, v1.2a R3, v1.2b R11): the screen, card or Tools
 * page that uses it. A capability without a page here leads nowhere.
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
  Throughput: 'tools/throughput',
  'Traffic generator': 'tools/traffic',
  'Station management': 'tools/stations',
}

export function capabilityLink(routerId: string, name: string): string | null {
  const path = Object.hasOwn(PATHS, name) ? PATHS[name] : undefined
  return path === undefined ? null : `/routers/${routerId}/${path}`
}
