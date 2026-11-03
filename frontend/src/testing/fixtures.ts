import type { RadioStatus, RouterItem, RouterStatus } from '../api/types'

const NOW = '2026-11-03T12:00:00+02:00'

function radio(up: boolean, htmode: string, stations: RadioStatus['stations'] = []): RadioStatus {
  return {
    name: 'radio0',
    band: '2g',
    up,
    disabled: !up,
    channel: '1',
    htmode,
    txpower_dbm: up ? 20 : null,
    ssids: up ? [{ name: 'OpenWrt', encryption: 'psk2', ifname: 'phy0-ap0' }] : [],
    stations,
  }
}

function status(lan: string, r: RadioStatus, dhcp: boolean): RouterStatus {
  return {
    read_at: NOW,
    uptime_s: 1786118,
    load: [0.16, 0.03, 0.01],
    mem_total_kb: 55104,
    mem_available_kb: 7484,
    radios: [r],
    interfaces: [{ name: 'lan', up: true, proto: 'static', ipv4: [lan] }],
    dhcp_server_on: dhcp,
  }
}

function record(id: string, name: string, host: string, auth: 'key' | 'none') {
  return { id, name, host, port: 22, username: 'root', auth, port_labels: {}, added_at: NOW }
}

const online = { online: true, since: NOW, error: null }

export const AP1: RouterItem = {
  record: record('ap1', 'AP1 · bench', '192.168.1.1', 'key'),
  health: online,
  status: status(
    '192.168.1.1/24',
    radio(true, 'HT20', [{ mac: 'f4:12:fa:f3:57:68', signal_dbm: -52, tx_mbps: 65, rx_mbps: 54, connected_s: 11520 }]),
    true,
  ),
  summary: null,
}

export const AP2: RouterItem = {
  record: record('ap2', 'AP2 · office', '192.168.1.2', 'key'),
  health: online,
  status: status('192.168.1.2/24', radio(false, 'HT40'), false),
  summary: null,
}

export const AP3: RouterItem = {
  record: record('ap3', 'AP3 · QA stands', '192.168.1.3', 'none'),
  health: { online: false, since: NOW, error: 'not connected yet' },
  status: null,
  summary: null,
}

export const ROUTERS: RouterItem[] = [AP1, AP2, AP3]
