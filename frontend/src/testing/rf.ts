import type { RfSample, StationSample } from '../api/types'

export const PANEL_SAMPLE: StationSample = {
  mac: 'f4:12:fa:f3:57:68',
  name: 'panel',
  signal_dbm: -52,
  signal_avg_dbm: -53,
  chains: [-54, -55],
  rx: { mbps: 54, mcs: null, width_mhz: 20, short_gi: false, mode: 'g' },
  tx: { mbps: 65, mcs: 7, width_mhz: 20, short_gi: false, mode: 'n20' },
  rx_pps: 200,
  rx_kbps: 41,
  tx_pps: 198,
  tx_kbps: 36,
  retry_pct: 4.1,
  failed_per_s: 0.2,
  rx_drops: 0,
  inactive_ms: 40,
  expected_mbps: 38,
  ack_signal_dbm: null,
}

/** An AP1 sample at 09:00:<second> with the given stations. */
export function rfSample(second: number, stations: StationSample[] = [PANEL_SAMPLE]): RfSample {
  return {
    at: `2026-11-05T09:00:${String(second).padStart(2, '0')}`,
    router_id: 'ap1',
    radio: 'radio0',
    ifname: 'phy0-ap0',
    radio_sample: { channel: 1, freq_mhz: 2412, width_mhz: 20, txpower_dbm: 20, busy_pct: 23, noise_dbm: null, ack_fail_per_s: 3 },
    stations,
    left: [],
  }
}
