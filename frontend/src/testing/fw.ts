import type { FirewallState, FwRuleConf, NetPlan, RuleView } from '../api/types'

function rule(section: string, name: string, src: string, extra: Partial<FwRuleConf> = {}): FwRuleConf {
  return {
    section,
    name,
    src,
    dest: null,
    proto: null,
    src_ip: [],
    dest_ip: [],
    src_port: null,
    dest_port: null,
    icmp_type: [],
    family: 'ipv4',
    target: 'ACCEPT',
    enabled: true,
    others: {},
    ...extra,
  }
}

function view(conf: FwRuleConf, effect: RuleView['effect'], packets: number): RuleView {
  return { conf, direction: 'input', zone: conf.src, target_class: conf.target === 'ACCEPT' ? 'accept' : 'block', effect, packets }
}

const RENEW = rule('cfg0592bd', 'Allow-DHCP-Renew', 'wan', { proto: 'udp', dest_port: '68' })
const PING = rule('cfg0692bd', 'Allow-Ping', 'wan', { proto: 'icmp', icmp_type: ['echo-request'] })
const IGMP = rule('cfg0792bd', 'Allow-IGMP', 'wan', { proto: 'igmp' })
const PANEL_PING = rule('cfg0892bd', 'Block-panel-ping', 'lan', { proto: 'icmp', src_ip: ['192.168.1.20'], icmp_type: ['echo-request'], target: 'DROP' })

/** AP1's firewall as the simulator shows it (tests/unit/api/test_fw_api.py), plus a lan rule that drops a panel's ping. */
export const AP1_FW: FirewallState = {
  router_id: 'ap1',
  available: true,
  reason: null,
  conf: {
    defaults: { section: 'cfg01e63d', values: { syn_flood: '1', input: 'REJECT', output: 'ACCEPT', forward: 'REJECT' } },
    zones: [
      { section: 'cfg02dc81', name: 'lan', networks: ['lan'], input: 'ACCEPT', output: 'ACCEPT', forward: 'ACCEPT', masq: false, mtu_fix: false, others: {} },
      { section: 'cfg03dc81', name: 'wan', networks: ['wan', 'wan6', 'lte'], input: 'REJECT', output: 'ACCEPT', forward: 'REJECT', masq: true, mtu_fix: true, others: {} },
    ],
    forwardings: [{ section: 'cfg04ad58', src: 'lan', dest: 'wan', enabled: true }],
    rules: [RENEW, PING, IGMP, PANEL_PING],
    redirects: [],
    nats: [],
    ipsets: [],
    includes: [],
  },
  rules: [view(RENEW, 'allows', 0), view(PING, 'allows', 12), view(IGMP, 'allows', 0), view(PANEL_PING, 'blocks', 318)],
  own_zone: 'lan',
  pc_ip: '192.168.1.10',
  ssh_port: 22,
  pins: [
    { id: 'ssh', name: 'Allow SSH from this PC', match: 'lan → this router · 192.168.1.10 · tcp 22', why: 'how this app reaches AP1 · bench', present: false },
    { id: 'dhcpdns', name: 'Allow DHCP and DNS', match: 'lan → this router · udp 67-68, udp/tcp 53', why: 'AP1 · bench serves DHCP and DNS on lan', present: false },
  ],
  objects: [
    { key: 'inet fw4', family: 'inet', table: 'fw4', chain: null, owner: 'fw4', writer: null, depends: null, rules: 31 },
    {
      key: 'inet fw4 chain BENCHSIPGUARD',
      family: 'inet',
      table: 'fw4',
      chain: 'BENCHSIPGUARD',
      owner: 'known',
      writer: 'dima_night',
      depends: 'dima_night expects BENCHSIPGUARD. Without it, SIP from the panels leaves the bench during soak runs.',
      rules: 2,
    },
    {
      key: 'bridge voipdscp',
      family: 'bridge',
      table: 'voipdscp',
      chain: null,
      owner: 'known',
      writer: 'voip_chain',
      depends: 'VoIP chain runs expect RTP and SIP marked EF. Changing it changes their results.',
      rules: 2,
    },
    { key: 'ip lab_scratch', family: 'ip', table: 'lab_scratch', chain: null, owner: 'unknown', writer: null, depends: 'Not created by fw4, this app or a known harness', rules: 3 },
  ],
  tc: [],
  counters: { 'Allow-DHCP-Renew': 0, 'Allow-Ping': 12, 'Allow-IGMP': 0, 'Block-panel-ping': 318 },
  custom: [
    {
      path: '/etc/nftables.d/10-custom-filter-chains.nft',
      name: '10-custom-filter-chains',
      content: '## The following chains are examples; they are not loaded by default.\n# chain user_pre_input {\n#\ttype filter hook input priority -1; policy accept;\n# }\n',
      from_image: true,
      lines: 4,
      comments_only: true,
    },
  ],
}

export const NOT_FW4: FirewallState = {
  ...AP1_FW,
  available: false,
  reason: 'This router does not run fw4 (firewall4); its firewall is not managed here.',
  rules: [],
  pins: [],
  objects: [],
}

function plan(lines: string[], warnings: string[] = [], rollback = true): NetPlan {
  return { router_id: 'ap1', screen: 'Firewall', lines, warnings, rollback, target_host: null, digest: 'fe11fe11fe11fe11' }
}

const S = 'uci -P /var/run/rpcd/uci-<session>'

/** lan input to Block all on AP1: the zone, both pins, and the rollback (compile_model). */
export const LAN_BLOCK_PLAN = plan(
  [
    "ubus call session create '{\"timeout\":300}'",
    'set -e',
    `${S} set firewall.cfg02dc81.input='REJECT'`,
    `${S} set firewall.owg_pin_ssh='rule'`,
    `${S} set firewall.owg_pin_ssh.src_ip='192.168.1.10'`,
    `${S} set firewall.owg_pin_dhcpdns='rule'`,
    'ubus call uci apply \'{"rollback":true,"timeout":60,"ubus_rpc_session":"<session>"}\'',
  ],
  [
    '1 rule no longer does anything in this model. They stay in the config, so switching back restores them; delete them here if you no longer need them.',
    'Applies with a 60 s rollback: if the app cannot reach AP1 · bench at 192.168.1.1 again and confirm, the router restores its previous firewall by itself.',
  ],
)

export const WAN_ALLOW_PLAN = plan([`${S} set firewall.cfg03dc81.input='ACCEPT'`])

export const ZONE_PLAN = plan([`${S} set firewall.cfg03dc81.masq='0'`])

/** AP1's `nft -a list ruleset` from the simulator, shortened to the tables the Tables tab edits. */
export const AP1_RULESET = [
  'table inet fw4 { # handle 1',
  '\tchain input_wan { # handle 20',
  '\t\tmeta nfproto ipv4 udp dport 68 counter packets 0 bytes 0 accept comment "!fw4: Allow-DHCP-Renew" # handle 21',
  '\t\ticmp type echo-request counter packets 12 bytes 1008 accept comment "!fw4: Allow-Ping" # handle 22',
  '\t\tjump reject_from_wan # handle 23',
  '\t}',
  'chain BENCHSIPGUARD { # handle 54',
  '\t\toifname { "eth0.2", "wwan0" } udp dport { 5060, 5061 } counter packets 0 bytes 0 reject # handle 55',
  '\t\toifname { "eth0.2", "wwan0" } tcp dport { 5060, 5061 } counter packets 7 bytes 420 reject # handle 56',
  '\t}',
  '}',
  'table bridge voipdscp { # handle 1',
  '\tset rtp { # handle 5',
  '\t\ttype inet_service',
  '\t\telements = { 5004 }',
  '\t}',
  '\tchain post { # handle 2',
  '\t\ttype filter hook postrouting priority 0; policy accept;',
  '\t\tudp dport 5004 ip dscp set ef counter packets 31 bytes 6200 # handle 3',
  '\t\tudp dport { 5060, 5061 } ip dscp set ef counter packets 0 bytes 0 # handle 4',
  '\t}',
  '}',
  'table ip lab_scratch { # handle 1',
  '\tchain pre { # handle 2',
  '\t\ttype filter hook prerouting priority 0; policy accept;',
  '\t\tip saddr 192.168.1.30 counter packets 0 bytes 0 # handle 3',
  '\t}',
  '}',
  '',
].join('\n')

const ROLLBACK = "mkdir -p /tmp/owg && start-stop-daemon -S -b -m -p /tmp/owg/rb-<rollback>.pid -x /bin/sh -- -c 'sleep 60; …'"

/** A new traffic rule (compile_sections): the uci add, its options, and the apply with rollback. */
export const RULE_ADD_PLAN = plan([
  'set -e',
  `r1=$(${S} add firewall rule)`,
  `${S} set firewall.$r1.name='Block-panel-ping'`,
  `${S} set firewall.$r1.target='DROP'`,
  'ubus call uci apply \'{"rollback":true,"timeout":60,"ubus_rpc_session":"<session>"}\'',
])

/** A custom rules file edit: backup, timer, the file, fw4's check, reload. */
export const CUSTOM_PLAN = plan([
  'set -e',
  'cp /etc/nftables.d/10-custom-filter-chains.nft /tmp/owg/rb-<rollback>.bak',
  ROLLBACK,
  "cat > /etc/nftables.d/10-custom-filter-chains.nft <<'OWG'",
  '# nothing',
  'OWG',
  'fw4 print > /tmp/owg/rb-<rollback>.check && nft -c -f /tmp/owg/rb-<rollback>.check',
  'fw4 reload',
])

/** voipdscp edited with the override (table_change): checked with nft -c, then applied. */
export const TABLE_EDIT_PLAN = plan(
  [
    'set -e',
    'nft list table bridge voipdscp > /tmp/owg/rb-<rollback>.nft',
    ROLLBACK,
    "nft -c -f /dev/stdin <<'OWG'",
    'delete table bridge voipdscp',
    'table bridge voipdscp {',
    'OWG',
    "nft -f /dev/stdin <<'OWG'",
  ],
  ['bridge voipdscp belongs to voip_chain: the change is written to the audit log as an override.'],
)

/** A new table (tables._add): nft's own `table inet owg_test { }`, checked, then loaded. */
export const TABLE_ADD_PLAN = plan([ROLLBACK, "nft -c -f /dev/stdin <<'OWG'", 'table inet owg_test {', '}', 'OWG'])
