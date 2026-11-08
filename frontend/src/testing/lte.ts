// Generated from the simulator (sim ap2, signal at its base values); do not edit by hand.
import type { AtResult, LteState, NetApplyResult, NetPlan, OptionRow } from '../api/types'

export const AP2_LTE: LteState = {
  "router_id": "ap2",
  "read_at": "2026-11-08T12:00:00",
  "available": true,
  "note": null,
  "device": "/dev/cdc-wdm0",
  "up": true,
  "pending": false,
  "uptime_s": 1000,
  "ipv4": "10.64.12.7",
  "rx_bytes": 1204331,
  "tx_bytes": 3876002,
  "registration": "registered",
  "radio": "lte",
  "roaming": false,
  "operator": "Partner",
  "operator_source": "at",
  "mcc": 425,
  "mnc": 1,
  "rssi": {
    "value": -67.0,
    "label": "good"
  },
  "rsrp": {
    "value": -95.0,
    "label": "fair"
  },
  "rsrq": {
    "value": -10.0,
    "label": "excellent"
  },
  "snr": {
    "value": 8.2,
    "label": "fair"
  },
  "opmode": "online",
  "modem": {
    "manufacturer": "BroadMobi",
    "model": "BM806C",
    "firmware": "M1.2.0_E1.0.3_A1.1.8",
    "operator": "Partner",
    "mode_order": 17,
    "at_port": "/dev/ttyUSB2"
  },
  "autoconnect_note": "This image's qmi.sh turns the modem's autoconnect off at every connect, so the setting has no effect",
  "missing": []
}

export const NO_LTE: LteState = {
  "router_id": "ap2",
  "read_at": "2026-11-08T12:00:00",
  "available": false,
  "note": "This router has no LTE interface (no qmi interface in its network config)",
  "device": null,
  "up": null,
  "pending": null,
  "uptime_s": null,
  "ipv4": null,
  "rx_bytes": null,
  "tx_bytes": null,
  "registration": null,
  "radio": null,
  "roaming": null,
  "operator": null,
  "operator_source": null,
  "mcc": null,
  "mnc": null,
  "rssi": null,
  "rsrp": null,
  "rsrq": null,
  "snr": null,
  "opmode": null,
  "modem": {
    "manufacturer": null,
    "model": null,
    "firmware": null,
    "operator": null,
    "mode_order": null,
    "at_port": null
  },
  "autoconnect_note": "This image's qmi.sh turns the modem's autoconnect off at every connect, so the setting has no effect",
  "missing": []
}

export const AP2_LTE_OPTIONS: OptionRow[] = [
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "device",
    "type": "device",
    "editor": "text",
    "value": "/dev/cdc-wdm0",
    "set_in_config": true,
    "control": "Device",
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "apn",
    "type": "string",
    "editor": "text",
    "value": "uinternet",
    "set_in_config": true,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "v6apn",
    "type": "string",
    "editor": "text",
    "value": null,
    "set_in_config": false,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "auth",
    "type": "string",
    "editor": "text",
    "value": "none",
    "set_in_config": true,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "username",
    "type": "string",
    "editor": "text",
    "value": null,
    "set_in_config": false,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "password",
    "type": "<hidden>",
    "editor": "secret",
    "value": null,
    "set_in_config": false,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "pincode",
    "type": "<hidden>",
    "editor": "secret",
    "value": null,
    "set_in_config": false,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "delay",
    "type": "uinteger",
    "editor": "number",
    "value": null,
    "set_in_config": false,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "modes",
    "type": "string",
    "editor": "text",
    "value": null,
    "set_in_config": false,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "pdptype",
    "type": "string",
    "editor": "text",
    "value": "ipv4",
    "set_in_config": true,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "profile",
    "type": "uinteger",
    "editor": "number",
    "value": null,
    "set_in_config": false,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "v6profile",
    "type": "uinteger",
    "editor": "number",
    "value": null,
    "set_in_config": false,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "devpath",
    "type": "string",
    "editor": "text",
    "value": null,
    "set_in_config": false,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "dhcp",
    "type": "bool",
    "editor": "switch",
    "value": null,
    "set_in_config": false,
    "control": "LTE screen",
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "dhcpv6",
    "type": "bool",
    "editor": "switch",
    "value": null,
    "set_in_config": false,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "sourcefilter",
    "type": "bool",
    "editor": "switch",
    "value": null,
    "set_in_config": false,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "delegate",
    "type": "bool",
    "editor": "switch",
    "value": null,
    "set_in_config": false,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "autoconnect",
    "type": "bool",
    "editor": "switch",
    "value": "0",
    "set_in_config": true,
    "control": "LTE screen",
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "plmn",
    "type": "uinteger",
    "editor": "number",
    "value": null,
    "set_in_config": false,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "timeout",
    "type": "uinteger",
    "editor": "number",
    "value": null,
    "set_in_config": false,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "mtu",
    "type": "uinteger",
    "editor": "number",
    "value": "1420",
    "set_in_config": true,
    "control": "MTU",
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "defaultroute",
    "type": "bool",
    "editor": "switch",
    "value": null,
    "set_in_config": false,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "peerdns",
    "type": "bool",
    "editor": "switch",
    "value": null,
    "set_in_config": false,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "renew",
    "type": "bool",
    "editor": "switch",
    "value": null,
    "set_in_config": false,
    "control": null,
    "writer": null
  },
  {
    "config": "network",
    "group": "interface",
    "section": "lte",
    "name": "metric",
    "type": "uinteger",
    "editor": "number",
    "value": "20",
    "set_in_config": true,
    "control": null,
    "writer": null
  }
]

export const LTE_APN_PLAN: NetPlan = {
  "router_id": "ap2",
  "screen": "Network",
  "lines": [
    "ubus call session create '{\"timeout\":300}'",
    "ubus call session grant '{\"objects\":[[\"network\",\"read\"],[\"network\",\"write\"]],\"scope\":\"uci\",\"ubus_rpc_session\":\"<session>\"}'",
    "set -e",
    "mkdir -p /var/run/rpcd/uci-<session>",
    "uci -P /var/run/rpcd/uci-<session> set network.lte.apn='internet'",
    "ubus call uci apply '{\"rollback\":true,\"timeout\":60,\"ubus_rpc_session\":\"<session>\"}'",
    "ubus call uci confirm '{\"ubus_rpc_session\":\"<session>\"}'",
    "ubus call session destroy '{\"ubus_rpc_session\":\"<session>\"}'"
  ],
  "warnings": [
    "Applies with a 60 s rollback: if the app cannot reach AP2 · office at 192.168.1.2 again and confirm, the router restores its previous network settings by itself."
  ],
  "rollback": true,
  "target_host": null,
  "digest": "6f864aab2f0c055e"
}

export const LTE_PASSWORD_PLAN: NetPlan = {
  "router_id": "ap2",
  "screen": "Network",
  "lines": [
    "ubus call session create '{\"timeout\":300}'",
    "ubus call session grant '{\"objects\":[[\"network\",\"read\"],[\"network\",\"write\"]],\"scope\":\"uci\",\"ubus_rpc_session\":\"<session>\"}'",
    "set -e",
    "mkdir -p /var/run/rpcd/uci-<session>",
    "uci -P /var/run/rpcd/uci-<session> set network.lte.password='<hidden>'",
    "ubus call uci apply '{\"rollback\":true,\"timeout\":60,\"ubus_rpc_session\":\"<session>\"}'",
    "ubus call uci confirm '{\"ubus_rpc_session\":\"<session>\"}'",
    "ubus call session destroy '{\"ubus_rpc_session\":\"<session>\"}'"
  ],
  "warnings": [
    "Applies with a 60 s rollback: if the app cannot reach AP2 · office at 192.168.1.2 again and confirm, the router restores its previous network settings by itself."
  ],
  "rollback": true,
  "target_host": null,
  "digest": "a757ab4d41fd39a1"
}

export const LTE_SETTINGS_RESULT: NetApplyResult = {
  "router_id": "ap2",
  "applied": true,
  "verified": true,
  "checks": [
    {
      "name": "reconnected",
      "ok": true,
      "detail": "AP2 · office answered at 192.168.1.2"
    },
    {
      "name": "confirmed",
      "ok": true,
      "detail": "the router keeps the change"
    },
    {
      "name": "interface lte",
      "ok": true,
      "detail": "up"
    },
    {
      "name": "saved",
      "ok": true,
      "detail": "the router has the change"
    }
  ],
  "error": null,
  "host": "192.168.1.2"
}

export const LTE_CONNECT_PLAN: NetPlan = {
  "router_id": "ap2",
  "screen": "LTE",
  "lines": [
    "ifup lte"
  ],
  "warnings": [],
  "rollback": false,
  "target_host": null,
  "digest": "2bc1a836a3ec45f5"
}

export const LTE_DISCONNECT_PLAN: NetPlan = {
  "router_id": "ap2",
  "screen": "LTE",
  "lines": [
    "ifdown lte"
  ],
  "warnings": [
    "AP2 · office's LTE session drops; devices that route through it lose the internet until it is back"
  ],
  "rollback": false,
  "target_host": null,
  "digest": "f8b003507573acf0"
}

export const LTE_REBOOT_PLAN: NetPlan = {
  "router_id": "ap2",
  "screen": "LTE",
  "lines": [
    "uqmi -s -d /dev/cdc-wdm0 -t 3000 --set-device-operating-mode low_power",
    "uqmi -s -d /dev/cdc-wdm0 -t 2000 --get-device-operating-mode",
    "uqmi -s -d /dev/cdc-wdm0 -t 3000 --set-device-operating-mode online",
    "uqmi -s -d /dev/cdc-wdm0 -t 2000 --get-device-operating-mode",
    "ifup lte"
  ],
  "warnings": [
    "AP2 · office's LTE session drops; devices that route through it lose the internet until it is back"
  ],
  "rollback": false,
  "target_host": null,
  "digest": "122ce939e51a98a0"
}

export const LTE_CONNECT_RESULT: NetApplyResult = {
  "router_id": "ap2",
  "applied": true,
  "verified": true,
  "checks": [
    {
      "name": "lte up",
      "ok": true,
      "detail": "up"
    },
    {
      "name": "lte_4 address",
      "ok": true,
      "detail": "10.64.12.7"
    }
  ],
  "error": null,
  "host": "192.168.1.2"
}

export const LTE_CONNECT_NO_ADDRESS: NetApplyResult = {
  "router_id": "ap2",
  "applied": true,
  "verified": true,
  "checks": [
    {
      "name": "lte up",
      "ok": true,
      "detail": "up"
    },
    {
      "name": "lte_4 address",
      "ok": null,
      "detail": "no address yet: waiting for the carrier's DHCP"
    }
  ],
  "error": null,
  "host": "192.168.1.2"
}

export const LTE_AT_CSQ: AtResult = {
  "command": "AT+CSQ",
  "lines": [
    "+CSQ: 20,99"
  ],
  "status": "OK",
  "error": null
}

export const LTE_AT_CFUN: AtResult = {
  "command": "AT+CFUN=0",
  "lines": [],
  "status": "OK",
  "error": null
}
