import type { ArmedFault, CaptureView, FaultsState, NetApplyResult, NetPlan } from '../api/types'
import { AP2_PORTS } from './ports'

export const PANEL = { name: 'panel', mac: 'f4:12:fa:f3:57:68', ip: '192.168.1.30', via: 'phy0-ap0', device: 'phy0-ap0' }
export const WIRED = { name: 'panel-eth', mac: 'e4:5f:01:aa:bb:01', ip: '192.168.1.31', via: 'wired', device: 'eth0.1' }

/** AP1's faults as the simulator shows them (tests/unit/api/test_faults_api.py): netdev, every netem table. */
export const AP1_FAULTS: FaultsState = {
  router_id: 'ap1',
  targets: [PANEL, WIRED],
  armed: [],
  caps: { family: 'netdev', distributions: ['paretonormal', 'pareto', 'normal'], ifb: true, conntrack: true, band: 'prio', netem: true },
  unavailable: {},
  wifi: [{ ifname: 'phy0-ap0', ssid: 'OpenWrt', up: true }],
  ports: { ...AP2_PORTS, router_id: 'ap1' },
}

/** AP2 as recorded 2026-11-07: bridge family, no distribution tables (normal / pareto greyed), ets instead of prio. */
export const AP2_FAULTS: FaultsState = { ...AP1_FAULTS, router_id: 'ap2', caps: { ...AP1_FAULTS.caps, family: 'bridge', distributions: [], band: 'ets' } }

export const ARMED: ArmedFault = {
  id: 'a1b2c3',
  kind: 'block',
  summary: 'Block rtp_in of panel (192.168.1.30) · 30 % loss',
  target: PANEL,
  device: 'phy0-ap0',
  clear: ['nft flush chain netdev benchfault fa1b2c3_to', 'nft delete chain netdev benchfault fa1b2c3_to'],
  armed_at: '2026-11-06T21:00:00',
  until: null,
}

function plan(lines: string[], warnings: string[] = []): NetPlan {
  return { router_id: 'ap1', screen: 'Faults', lines, warnings, rollback: false, target_host: null, digest: 'fa017fa017fa017f' }
}

const RTP = 'add rule netdev benchfault fa1b2c3_to ip daddr 192.168.1.30 udp dport { 5004 } numgen random mod 100 < 30 counter drop comment "owg:a1b2c3"'
const TIMER = "mkdir -p /tmp/owg && start-stop-daemon -S -b -m -p /tmp/owg/fault-a1b2c3.pid -x /bin/sh -- -c 'sleep 60; …'"

export function blockPlan(hold: boolean): NetPlan {
  return plan(['set -e', 'nft add table netdev benchfault', RTP, ...(hold ? [TIMER] : []), "printf '%s\"armed_at\":%s}\\n' '…' \"$(date +%s)\" > /tmp/owg/fault-a1b2c3.json"])
}

export const ARMED_RESULT: NetApplyResult = {
  router_id: 'ap1',
  applied: true,
  verified: true,
  error: null,
  host: null,
  checks: [
    { name: 'fault a1b2c3', ok: true, detail: 'chain fa1b2c3_to on egress, counter readable' },
    { name: 'record', ok: true, detail: '/tmp/owg/fault-a1b2c3.json' },
  ],
}

export const CLEAR_PLAN = plan(['nft flush chain netdev benchfault fa1b2c3_to', 'nft delete chain netdev benchfault fa1b2c3_to', 'rm -f /tmp/owg/fault-a1b2c3.*', 'nft delete table netdev benchfault 2>/dev/null'])

export const CLEARED_DURING_RUN: NetApplyResult = {
  ...ARMED_RESULT,
  error: 'Cleared although Bench Guard is live (dima_night.py started 21:04 (PID 18244))',
  checks: [{ name: 'cleared', ok: true, detail: 'no fault chains left' }],
}

export const CAPTURING: CaptureView = {
  id: 'c1',
  router_id: 'ap1',
  device: 'br-lan',
  filter: 'udp',
  started_at: '2026-11-06T21:10:00',
  duration_s: 60,
  output: 'file',
  bytes: 0,
  running: true,
  path: null,
  error: null,
}

export const CAPTURED: CaptureView = {
  ...CAPTURING,
  bytes: 48213,
  running: false,
  path: 'C:\\Users\\bench\\Documents\\OpenWrtGUI\\captures\\ap1-br-lan-20261106-211000.pcap',
}
