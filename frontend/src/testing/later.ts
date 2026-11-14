// ap4, the simulated later image (v1.0a2 D7): what its endpoints answer, written from the simulator's fixtures
// (tests/fixtures/sim/later/ap4.json, net/ap4.uci). testing/system.ts is generated from ap2; ap4 is not there.
import type { FstabState, IptablesState, NetPlan, PluginState } from '../api/types'

const rule = (num: number, packets: number, bytes: number, target: string, prot: string, inp: string, source: string, options: string, comment: string | null) => ({
  num,
  packets,
  bytes,
  target,
  prot,
  opt: '--',
  inp,
  out: '*',
  source,
  destination: '0.0.0.0/0',
  options,
  comment,
})

export const AP4_IPTABLES: IptablesState = {
  iptables: true,
  ip6tables: true,
  tables: [
    {
      program: 'iptables',
      table: 'filter',
      error: null,
      chains: [
        {
          name: 'INPUT',
          policy: 'ACCEPT',
          packets: 1200,
          bytes: 96000,
          references: null,
          rules: [rule(1, 640, 51200, 'ACCEPT', 'all', 'lo', '0.0.0.0/0', '', null), rule(2, 12, 720, 'DROP', 'tcp', '*', '10.9.8.0/24', 'tcp dpt:22', 'Drop SSH from the lab net')],
        },
        { name: 'FORWARD', policy: 'DROP', packets: 0, bytes: 0, references: null, rules: [] },
        { name: 'OUTPUT', policy: 'ACCEPT', packets: 900, bytes: 72000, references: null, rules: [] },
        { name: 'lab_user', policy: null, packets: null, bytes: null, references: 0, rules: [] },
      ],
    },
    { program: 'iptables', table: 'nat', error: null, chains: [] },
  ],
}

export const AP4_RESET_PLAN: NetPlan = {
  router_id: 'ap4',
  screen: 'Firewall',
  lines: ['iptables -Z', 'ip6tables -Z'],
  warnings: ["Resets the filter table's counters only, as LuCI does: nat, mangle and raw keep theirs."],
  rollback: false,
  target_host: null,
  digest: '2b3c4d5e6f7a8b9c',
}

export const AP4_FSTAB: FstabState = {
  block: true,
  settings: { anon_swap: false, anon_mount: false, auto_swap: true, auto_mount: true, check_fs: false, delay_root: 5 },
  global_section: 'cfg01a7f1',
  entries: [
    { section: 'cfg02a7f1', kind: 'mount', enabled: true, uuid: '5e1f6c2a-9b0d-4c3e-8f7a-1d2c3b4a5e6f', label: null, device: null, target: '/mnt/usb', fstype: null, options: null },
    { section: 'cfg03a7f1', kind: 'swap', enabled: false, uuid: null, label: null, device: '/dev/sda2', target: null, fstype: null, options: null },
  ],
  devices: [
    { dev: '/dev/sda1', uuid: '5e1f6c2a-9b0d-4c3e-8f7a-1d2c3b4a5e6f', label: 'usb', type: 'ext4', size: 15728640000, mount: '/mnt/usb' },
    { dev: '/dev/sda2', uuid: '8a3b1c4d-2e5f-4a6b-9c7d-0e1f2a3b4c5d', label: null, type: 'swap', size: 1073741824, mount: null },
  ],
  missing: [],
}

export const AP4_FSTAB_OFF_PLAN: NetPlan = {
  router_id: 'ap4',
  screen: 'System',
  lines: ['set -e', "uci set fstab.cfg02a7f1.enabled='0'", 'uci commit fstab', '/sbin/block mount'],
  warnings: [],
  rollback: false,
  target_host: null,
  digest: '1a2b3c4d5e6f7a8b',
}

export const AP4_PLUGINS: PluginState = {
  enabled: true,
  global_section: true,
  groups: [
    { key: 'auth_login', enabled: false },
    { key: 'http_headers', enabled: true },
  ],
  plugins: [
    {
      id: '0123456789abcdef0123456789abcdef',
      group: 'auth_login',
      name: 'Gone plugin',
      title: '',
      description: '',
      installed: false,
      configured: true,
      enabled: false,
      options: {},
    },
    {
      id: 'c0ffee2cf63e160c091224d95d69cdff',
      group: 'http_headers',
      name: 'Content-Security-Policy',
      title: 'Content Security Policy',
      description: 'Sets the Content-Security-Policy header on every LuCI response.',
      installed: true,
      configured: true,
      enabled: true,
      options: { mode: 'strict' },
    },
  ],
  missing: [],
}

export const AP4_PLUGIN_OFF_PLAN: NetPlan = {
  router_id: 'ap4',
  screen: 'System',
  lines: ['set -e', 'uci -q delete luci_plugins.c0ffee2cf63e160c091224d95d69cdff.enabled', 'uci commit luci_plugins'],
  warnings: [],
  rollback: false,
  target_host: null,
  digest: '0f1e2d3c4b5a6978',
}
