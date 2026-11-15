import type { BridgeState, NetPlan } from '../api/types'

/** ap5's bridge as the API returns it (v1.0a3): the PC on lan3, VLAN 1 carries lan, VLAN 10 carries iot. */
export const AP5_BRIDGE: BridgeState = {
  router_id: 'ap5',
  bridge: 'switch',
  editable: true,
  blocker: null,
  issues: [],
  ports: [
    { name: 'lan1', link: false, may_carry: false },
    { name: 'lan2', link: false, may_carry: false },
    { name: 'lan3', link: true, may_carry: true },
    { name: 'lan4', link: false, may_carry: false },
  ],
  vlans: [
    {
      section: 'cfg040f15',
      vlan: 1,
      local: true,
      members: { lan1: 'u', lan2: 'u', lan3: 'u', lan4: 'u' },
      entries: { lan1: 'lan1', lan2: 'lan2', lan3: 'lan3', lan4: 'lan4' },
      used_by: ['lan'],
      own: true,
    },
    {
      section: 'cfg050f15',
      vlan: 10,
      local: true,
      members: { lan1: 't', lan4: 't' },
      entries: { lan1: 'lan1:t', lan4: 'lan4:t' },
      used_by: ['iot'],
      own: false,
    },
  ],
  own_interface: 'lan',
  own_vlan: 1,
  runtime: [],
}

export const BRIDGE_PLAN: NetPlan = {
  router_id: 'ap5',
  screen: 'Ports',
  lines: ['uci -P /var/run/rpcd/uci-<session> -q delete network.cfg040f15.ports', "uci -P /var/run/rpcd/uci-<session> add_list network.cfg040f15.ports='lan1'"],
  warnings: ['Applies with a 60 s rollback: if the app cannot reach AP5 · DSA image at 192.168.1.7 again and confirm, the router restores its previous network settings by itself.'],
  rollback: true,
  target_host: '192.168.1.7',
  digest: '0123456789abcdef',
}
