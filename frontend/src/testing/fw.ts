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
