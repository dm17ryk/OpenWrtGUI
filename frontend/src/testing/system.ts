// Generated from the simulator (sim ap2); do not edit by hand.
import type {
  Connections,
  CronState,
  DiagResult,
  LogEntry,
  NetApplyResult,
  NetPlan,
  ProcessList,
  SystemOverview,
  SystemServiceRow,
  SystemSettingsOut,
  TimeZones,
} from '../api/types'

export const AP2_SYSTEM: SystemOverview = {
  "router_id": "ap2",
  "read_at": "2026-11-09T12:00:00",
  "model": "D-Link DWR-921 C3 (U-Boot)",
  "board_name": "dlink,dwr-921-c3-uboot",
  "kernel": "6.18.41",
  "hostname": "OpenWrt",
  "system": "MediaTek MT7620N ver:2 eco:6",
  "release": "OpenWrt SNAPSHOT r35692-b8bffeefdf",
  "revision": "r35692-b8bffeefdf",
  "localtime": 1793707200,
  "uptime_s": 86400,
  "load": [
    0.16,
    0.03,
    0.01
  ],
  "memory_total": 56426496,
  "memory_available": 7663616,
  "root_total_kib": 5056,
  "root_free_kib": 4652,
  "tmp_total_kib": 27552,
  "tmp_free_kib": 27028,
  "missing": []
}

export const AP2_SETTINGS: SystemSettingsOut = {
  "hostname": "OpenWrt",
  "zonename": "UTC",
  "ntp_client": true,
  "ntp_server": false,
  "ntp_servers": [
    "0.openwrt.pool.ntp.org",
    "1.openwrt.pool.ntp.org",
    "2.openwrt.pool.ntp.org",
    "3.openwrt.pool.ntp.org"
  ],
  "log_size": 128,
  "log_ip": "",
  "log_port": null,
  "log_proto": null
}

export const AP2_ZONES: TimeZones = {
  "zones": [
    "UTC",
    "America/New_York",
    "Asia/Jerusalem",
    "Etc/GMT",
    "Europe/Berlin",
    "Europe/London"
  ],
  "note": null
}

export const AP2_HOSTNAME_PLAN: NetPlan = {
  "router_id": "ap2",
  "screen": "System",
  "lines": [
    "set -e",
    "uci set system.cfg01e48a.hostname='bench-ap2'",
    "uci commit system",
    "/etc/init.d/system reload"
  ],
  "warnings": [],
  "rollback": false,
  "target_host": null,
  "digest": "6ee1975c89f32d9e"
}

export const AP2_SERVICES: SystemServiceRow[] = [
  {
    "name": "boot",
    "enabled": true,
    "running": false,
    "start": 10,
    "stop": null,
    "protected": null
  },
  {
    "name": "bootcount",
    "enabled": true,
    "running": false,
    "start": 99,
    "stop": null,
    "protected": null
  },
  {
    "name": "cron",
    "enabled": true,
    "running": false,
    "start": 50,
    "stop": null,
    "protected": null
  },
  {
    "name": "dnsmasq",
    "enabled": true,
    "running": true,
    "start": 19,
    "stop": null,
    "protected": null
  },
  {
    "name": "done",
    "enabled": true,
    "running": false,
    "start": 95,
    "stop": null,
    "protected": null
  },
  {
    "name": "dropbear",
    "enabled": true,
    "running": true,
    "start": 19,
    "stop": null,
    "protected": "This app reaches the router over SSH (dropbear): stopping or disabling it cuts the app off"
  },
  {
    "name": "dwr921-internet-led",
    "enabled": true,
    "running": true,
    "start": 97,
    "stop": null,
    "protected": null
  },
  {
    "name": "firewall",
    "enabled": true,
    "running": false,
    "start": 19,
    "stop": null,
    "protected": "Stopping the firewall drops the router's rules; restart applies them again"
  },
  {
    "name": "gpio_switch",
    "enabled": true,
    "running": false,
    "start": 94,
    "stop": null,
    "protected": null
  },
  {
    "name": "led",
    "enabled": true,
    "running": false,
    "start": 96,
    "stop": null,
    "protected": null
  },
  {
    "name": "log",
    "enabled": true,
    "running": true,
    "start": 12,
    "stop": null,
    "protected": "The Logs tab reads the system log from log (logd)"
  },
  {
    "name": "network",
    "enabled": true,
    "running": true,
    "start": 20,
    "stop": null,
    "protected": "network carries this app's connection to the router"
  },
  {
    "name": "odhcpd",
    "enabled": false,
    "running": false,
    "start": 35,
    "stop": null,
    "protected": null
  },
  {
    "name": "openssl",
    "enabled": true,
    "running": false,
    "start": 13,
    "stop": null,
    "protected": null
  },
  {
    "name": "packet_steering",
    "enabled": true,
    "running": false,
    "start": 25,
    "stop": null,
    "protected": null
  },
  {
    "name": "radius",
    "enabled": true,
    "running": false,
    "start": 30,
    "stop": null,
    "protected": null
  },
  {
    "name": "rpcd",
    "enabled": true,
    "running": true,
    "start": 12,
    "stop": null,
    "protected": "The app's settings changes and the LuCI pages go through rpcd"
  },
  {
    "name": "socat",
    "enabled": true,
    "running": false,
    "start": 99,
    "stop": null,
    "protected": null
  },
  {
    "name": "sysctl",
    "enabled": true,
    "running": false,
    "start": 11,
    "stop": null,
    "protected": null
  },
  {
    "name": "sysfixtime",
    "enabled": true,
    "running": false,
    "start": 0,
    "stop": null,
    "protected": null
  },
  {
    "name": "sysntpd",
    "enabled": true,
    "running": true,
    "start": 98,
    "stop": null,
    "protected": null
  },
  {
    "name": "system",
    "enabled": true,
    "running": false,
    "start": 10,
    "stop": null,
    "protected": null
  },
  {
    "name": "ucitrack",
    "enabled": true,
    "running": false,
    "start": 80,
    "stop": null,
    "protected": null
  },
  {
    "name": "uhttpd",
    "enabled": true,
    "running": true,
    "start": 50,
    "stop": null,
    "protected": "LuCI pages open through uhttpd"
  },
  {
    "name": "umount",
    "enabled": false,
    "running": false,
    "start": null,
    "stop": null,
    "protected": null
  },
  {
    "name": "urandom_seed",
    "enabled": true,
    "running": false,
    "start": 99,
    "stop": null,
    "protected": null
  },
  {
    "name": "urngd",
    "enabled": true,
    "running": true,
    "start": 0,
    "stop": null,
    "protected": null
  },
  {
    "name": "wpad",
    "enabled": true,
    "running": true,
    "start": 19,
    "stop": null,
    "protected": null
  }
]

export const AP2_CRONTAB: CronState = {
  "text": "",
  "tasks": [],
  "cron_enabled": true,
  "cron_running": false,
  "note": null
}

export const AP2_RC_LOCAL = "# Put your custom commands here that should be executed once\n# the system init finished. By default this file does nothing.\n\nexit 0\n"

export const AP2_PROCESSES: ProcessList = {
  "rows": [
    {
      "pid": 18424,
      "ppid": 18423,
      "user": "root",
      "state": "R",
      "mem_kib": 1108,
      "mem_pct": 2.0,
      "cpu_pct": 9.0,
      "command": "top -bn1"
    },
    {
      "pid": 22547,
      "ppid": 22544,
      "user": "network",
      "state": "S",
      "mem_kib": 4796,
      "mem_pct": 9.0,
      "cpu_pct": 0.0,
      "command": "/usr/sbin/hostapd -s -g /var/run/hostapd/global"
    },
    {
      "pid": 1517,
      "ppid": 1513,
      "user": "network",
      "state": "S",
      "mem_kib": 3072,
      "mem_pct": 6.0,
      "cpu_pct": 0.0,
      "command": "/usr/sbin/wpa_supplicant -n -s -g /var/run/wpa_supplicant/global"
    },
    {
      "pid": 1582,
      "ppid": 1,
      "user": "root",
      "state": "S",
      "mem_kib": 2180,
      "mem_pct": 4.0,
      "cpu_pct": 0.0,
      "command": "/sbin/netifd -l 2"
    },
    {
      "pid": 1096,
      "ppid": 1,
      "user": "root",
      "state": "S",
      "mem_kib": 1908,
      "mem_pct": 3.0,
      "cpu_pct": 0.0,
      "command": "/sbin/rpcd -s /var/run/ubus/ubus.sock -t 30"
    },
    {
      "pid": 1644,
      "ppid": 1642,
      "user": "dnsmasq",
      "state": "S",
      "mem_kib": 1752,
      "mem_pct": 3.0,
      "cpu_pct": 0.0,
      "command": "/usr/sbin/dnsmasq -C /var/etc/dnsmasq.conf.cfg01411c -k"
    },
    {
      "pid": 1821,
      "ppid": 1,
      "user": "root",
      "state": "S",
      "mem_kib": 1460,
      "mem_pct": 3.0,
      "cpu_pct": 0.0,
      "command": "/usr/sbin/uhttpd -f -h /www -r OpenWrt -x /cgi-bin -u /ubus"
    },
    {
      "pid": 1018,
      "ppid": 1,
      "user": "logd",
      "state": "S",
      "mem_kib": 1312,
      "mem_pct": 2.0,
      "cpu_pct": 0.0,
      "command": "/sbin/logd -S 128"
    },
    {
      "pid": 1,
      "ppid": 0,
      "user": "root",
      "state": "S",
      "mem_kib": 1228,
      "mem_pct": 2.0,
      "cpu_pct": 0.0,
      "command": "/sbin/procd"
    },
    {
      "pid": 2464,
      "ppid": 1,
      "user": "root",
      "state": "S",
      "mem_kib": 1040,
      "mem_pct": 2.0,
      "cpu_pct": 0.0,
      "command": "{dwr921-internet} /bin/sh /usr/sbin/dwr921-internet-led"
    },
    {
      "pid": 2675,
      "ppid": 2650,
      "user": "ntp",
      "state": "S",
      "mem_kib": 908,
      "mem_pct": 2.0,
      "cpu_pct": 0.0,
      "command": "/usr/sbin/ntpd -n -N -S /usr/sbin/ntpd-hotplug -p 0.openwrt.pool.ntp.org"
    },
    {
      "pid": 1402,
      "ppid": 1,
      "user": "root",
      "state": "S",
      "mem_kib": 896,
      "mem_pct": 2.0,
      "cpu_pct": 0.0,
      "command": "/usr/sbin/dropbear -F -P /var/run/dropbear.main.pid -p 22 -K 300 -T 3"
    },
    {
      "pid": 500,
      "ppid": 1,
      "user": "ubus",
      "state": "S",
      "mem_kib": 780,
      "mem_pct": 1.0,
      "cpu_pct": 0.0,
      "command": "/sbin/ubusd"
    },
    {
      "pid": 2,
      "ppid": 0,
      "user": "root",
      "state": "SW",
      "mem_kib": 0,
      "mem_pct": 0.0,
      "cpu_pct": 0.0,
      "command": "[kthreadd]"
    }
  ],
  "cpu": "0% usr   9% sys   0% nic  90% idle   0% io   0% irq   0% sirq",
  "column": "RSS"
}

export const AP2_SYSLOG: LogEntry[] = [
  {
    "time": "Sun Nov  8 09:00:04 2026",
    "seconds": null,
    "facility": "daemon",
    "level": "info",
    "source": "dnsmasq",
    "pid": 1644,
    "message": "started, version 2.90 cachesize 1000"
  },
  {
    "time": "Sun Nov  8 09:00:05 2026",
    "seconds": null,
    "facility": "daemon",
    "level": "notice",
    "source": "netifd",
    "pid": null,
    "message": "Interface 'lte' is now up"
  },
  {
    "time": "Sun Nov  8 09:00:06 2026",
    "seconds": null,
    "facility": "daemon",
    "level": "info",
    "source": "dnsmasq",
    "pid": 1644,
    "message": "using nameserver 10.64.12.1#53"
  },
  {
    "time": "Sun Nov  8 09:00:09 2026",
    "seconds": null,
    "facility": "user",
    "level": "notice",
    "source": "dwr921-internet-led",
    "pid": null,
    "message": "internet up via lte"
  },
  {
    "time": "Sun Nov  8 09:01:11 2026",
    "seconds": null,
    "facility": "daemon",
    "level": "err",
    "source": "uhttpd",
    "pid": 1821,
    "message": "luci: accepted login on / for root from 192.168.1.10"
  },
  {
    "time": "Sun Nov  8 09:05:00 2026",
    "seconds": null,
    "facility": "daemon",
    "level": "warn",
    "source": "odhcpd",
    "pid": 1700,
    "message": "No default route present, overriding ra_lifetime to 0!"
  },
  {
    "time": "Sun Nov  8 15:29:02 2026",
    "seconds": null,
    "facility": "authpriv",
    "level": "info",
    "source": "dropbear",
    "pid": 24543,
    "message": "Child connection from 192.168.1.10:53498"
  },
  {
    "time": "Sun Nov  8 15:29:02 2026",
    "seconds": null,
    "facility": "authpriv",
    "level": "notice",
    "source": "dropbear",
    "pid": 24543,
    "message": "Pubkey auth succeeded for 'root' with ssh-rsa key from 192.168.1.10:53498"
  },
  {
    "time": "Sun Nov  8 15:29:10 2026",
    "seconds": null,
    "facility": "daemon",
    "level": "notice",
    "source": "netifd",
    "pid": null,
    "message": "radio0 (24611): wifi-scripts: Tearing down phy0"
  },
  {
    "time": "Sun Nov  8 15:29:11 2026",
    "seconds": null,
    "facility": "daemon",
    "level": "notice",
    "source": "netifd",
    "pid": null,
    "message": "radio0 (24624): wifi-scripts: Setting country code to IL"
  },
  {
    "time": "Sun Nov  8 15:29:12 2026",
    "seconds": null,
    "facility": "authpriv",
    "level": "info",
    "source": "dropbear",
    "pid": 24543,
    "message": "Exit (root) from <192.168.1.10:53498>: Disconnect received"
  },
  {
    "time": "Sun Nov  8 15:30:00 2026",
    "seconds": null,
    "facility": "cron",
    "level": "info",
    "source": "crond",
    "pid": 2600,
    "message": "crond (busybox 1.37.0) started, log level 5"
  }
]

export const AP2_KERNEL: LogEntry[] = [
  {
    "time": null,
    "seconds": 0.0,
    "facility": "kern",
    "level": "info",
    "source": "kernel",
    "pid": null,
    "message": "Memory: 54840K/65536K available"
  },
  {
    "time": null,
    "seconds": 2.345678,
    "facility": "kern",
    "level": "info",
    "source": "kernel",
    "pid": null,
    "message": "rt2800_wmac 10180000.wmac: loaded eeprom from mtd"
  },
  {
    "time": null,
    "seconds": 3.456789,
    "facility": "kern",
    "level": "info",
    "source": "kernel",
    "pid": null,
    "message": "mtk_soc_eth 10100000.ethernet eth0: mediatek frame engine at 0xb0100000, irq 5"
  },
  {
    "time": null,
    "seconds": 8.765432,
    "facility": "kern",
    "level": "warning",
    "source": "kernel",
    "pid": null,
    "message": "jffs2: notice: (433) jffs2_build_xattr_subsystem: complete building xattr subsystem"
  },
  {
    "time": null,
    "seconds": 12.0,
    "facility": "kern",
    "level": "info",
    "source": "kernel",
    "pid": null,
    "message": "usb 1-1: new high-speed USB device number 2 using ehci-platform"
  },
  {
    "time": null,
    "seconds": 13.1,
    "facility": "kern",
    "level": "info",
    "source": "kernel",
    "pid": null,
    "message": "qmi_wwan 1-1:1.4: cdc-wdm0: USB WDM device"
  },
  {
    "time": null,
    "seconds": 13.2,
    "facility": "kern",
    "level": "info",
    "source": "kernel",
    "pid": null,
    "message": "option 1-1:1.0: GSM modem (1-port) converter detected"
  },
  {
    "time": null,
    "seconds": 20.5,
    "facility": "kern",
    "level": "info",
    "source": "kernel",
    "pid": null,
    "message": "br-lan: port 1(eth0.1) entered forwarding state"
  }
]

export const AP2_CONNECTIONS: Connections = {
  "rows": [
    {
      "proto": "tcp",
      "src": "192.168.1.10",
      "dst": "192.168.1.2",
      "sport": 53498,
      "dport": 22,
      "state": "ESTABLISHED",
      "bytes": 10000
    },
    {
      "proto": "udp",
      "src": "192.168.1.2",
      "dst": "10.64.12.1",
      "sport": 5353,
      "dport": 53,
      "state": null,
      "bytes": 60
    },
    {
      "proto": "tcp",
      "src": "192.168.1.10",
      "dst": "192.168.1.2",
      "sport": 53510,
      "dport": 80,
      "state": "TIME_WAIT",
      "bytes": 3300
    }
  ],
  "note": null
}

export const AP2_REBOOT_PLAN: NetPlan = {
  "router_id": "ap2",
  "screen": "System",
  "lines": [
    "mkdir -p /tmp/owg && start-stop-daemon -S -b -m -p /tmp/owg/reboot.pid -x /bin/sh -- -c 'sleep 2; reboot; rm -f /tmp/owg/reboot.*'"
  ],
  "warnings": [
    "AP2 · office is offline for about 60-90 s while it restarts",
    "LTE and Wi-Fi come back with the router; the LuCI bridge and the terminal reconnect by themselves"
  ],
  "rollback": false,
  "target_host": null,
  "digest": "5ca0ea30cacc3626"
}

export const AP2_PING: DiagResult = {
  "tool": "ping",
  "target": "192.168.1.10",
  "command": "timeout -s KILL 25 ping -c 4 -W 2 '192.168.1.10'",
  "output": "PING 192.168.1.10 (192.168.1.10): 56 data bytes\n64 bytes from 192.168.1.10: seq=0 ttl=64 time=0.512 ms\n64 bytes from 192.168.1.10: seq=1 ttl=64 time=0.513 ms\n64 bytes from 192.168.1.10: seq=2 ttl=64 time=0.514 ms\n64 bytes from 192.168.1.10: seq=3 ttl=64 time=0.515 ms\n\n--- 192.168.1.10 ping statistics ---\n4 packets transmitted, 4 packets received, 0% loss\n",
  "exit_status": 0
}

export const AP2_HOSTNAME_RESULT: NetApplyResult = {
  "router_id": "ap2",
  "applied": true,
  "verified": true,
  "checks": [
    {
      "name": "saved",
      "ok": true,
      "detail": "the router has the change"
    },
    {
      "name": "hostname",
      "ok": true,
      "detail": "bench-ap2"
    }
  ],
  "error": null,
  "host": "192.168.1.2"
}

export const AP2_SERVICE_PLAN: NetPlan = {
  "router_id": "ap2",
  "screen": "System",
  "lines": [
    "/etc/init.d/sysntpd restart"
  ],
  "warnings": [],
  "rollback": false,
  "target_host": null,
  "digest": "b641a0defc358848"
}

export const AP2_SERVICE_RESULT: NetApplyResult = {
  "router_id": "ap2",
  "applied": true,
  "verified": true,
  "checks": [
    {
      "name": "service sysntpd",
      "ok": true,
      "detail": "running"
    }
  ],
  "error": null,
  "host": "192.168.1.2"
}

export const AP2_CRON_PLAN: NetPlan = {
  "router_id": "ap2",
  "screen": "System",
  "lines": [
    "mkdir -p /etc/crontabs && cat > /etc/crontabs/root <<'OWG'",
    "*/5 * * * * logger owg-test",
    "OWG",
    "/etc/init.d/cron restart"
  ],
  "warnings": [],
  "rollback": false,
  "target_host": null,
  "digest": "f34300eee0bb713d"
}

export const AP2_CRON_RESULT: NetApplyResult = {
  "router_id": "ap2",
  "applied": true,
  "verified": true,
  "checks": [
    {
      "name": "saved",
      "ok": true,
      "detail": "the router has the new file"
    },
    {
      "name": "cron",
      "ok": true,
      "detail": "running"
    }
  ],
  "error": null,
  "host": "192.168.1.2"
}
