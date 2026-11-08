// Generated from the simulator (sim ap1 and ap2 with the mini images imported); do not edit by hand.
import type { ChecklistInfo, DiscoveryState, FirmwareCheck, FlashPlanOut, NetPlan, ProfileOut, ToolCard } from '../api/types'

export const MINI_PROFILE: ProfileOut = {
  "key": {
    "board": "dlink,dwr-921-c3-uboot",
    "revision": "r35692-b8bffeefdf",
    "sha256": "4ede1b92baa19361c0b8bde87dbee473de75a9409351f24104b415bce32fcec0"
  },
  "label": "dlink,dwr-921-c3-uboot r35692-b8bffeefdf",
  "folder": "r35692-b8bffeefdf-4ede1b92baa1",
  "source": "image",
  "image_name": "mini-r35692.bin",
  "image_size": 65840,
  "boards": [
    "dlink,dwr-921-c3-uboot"
  ],
  "revision": "r35692-b8bffeefdf",
  "packages": 7,
  "custom": [
    "dwr921-diag",
    "dwr921-internet-led",
    "dwr921-portctl"
  ],
  "built_at": "2026-11-08T12:00:00"
}
export const NEWER_PROFILE: ProfileOut = {
  "key": {
    "board": "dlink,dwr-921-c3-uboot",
    "revision": "r35700-0c0ffee000",
    "sha256": "06988f7bb2169f05cdf39b84b3fde142f1009da81b4af6da3af08408f84afc41"
  },
  "label": "dlink,dwr-921-c3-uboot r35700-0c0ffee000",
  "folder": "r35700-0c0ffee000-06988f7bb216",
  "source": "image",
  "image_name": "mini-r35700.bin",
  "image_size": 65840,
  "boards": [
    "dlink,dwr-921-c3-uboot"
  ],
  "revision": "r35700-0c0ffee000",
  "packages": 7,
  "custom": [
    "dwr921-diag",
    "dwr921-internet-led",
    "dwr921-portctl"
  ],
  "built_at": "2026-11-08T12:00:00"
}
export const AP1_DISCOVERY: DiscoveryState = {
  "router_id": "ap1",
  "read_at": "2026-11-08T11:51:58.911712",
  "board": "dlink,dwr-921-c3-uboot",
  "revision": "r35692-b8bffeefdf",
  "profile": {
    "board": "dlink,dwr-921-c3-uboot",
    "revision": "r35692-b8bffeefdf",
    "sha256": "4ede1b92baa19361c0b8bde87dbee473de75a9409351f24104b415bce32fcec0"
  },
  "match_note": null,
  "has_overlay": true,
  "overlay": {
    "added": [
      {
        "path": "/etc/init.d/wifi-mirror",
        "kind": "file",
        "size": 47,
        "mode": "-rwxr-xr-x",
        "target": null
      },
      {
        "path": "/usr/bin/iperf3",
        "kind": "file",
        "size": 8,
        "mode": "-rwxr-xr-x",
        "target": null
      },
      {
        "path": "/usr/sbin/wifi-mirror",
        "kind": "file",
        "size": 95,
        "mode": "-rwxr-xr-x",
        "target": null
      }
    ],
    "replaced": [
      {
        "path": "/etc/config/dropbear",
        "kind": "file",
        "size": 93,
        "mode": "-rw-r--r--",
        "target": null
      },
      {
        "path": "/lib/apk/db/installed",
        "kind": "file",
        "size": 1804,
        "mode": "-rw-r--r--",
        "target": null
      }
    ],
    "deleted": [
      "/etc/uci-defaults/20_dwr921_c3_uboot_luci"
    ],
    "unreadable": 0
  },
  "packages": {
    "added": [
      {
        "name": "iperf3",
        "version": "3.17.1-r2",
        "description": "Internet Protocol bandwidth measuring tool",
        "origin": "feeds/packages/net/iperf3",
        "license": "BSD-3-Clause",
        "url": "https://software.es.net/iperf/",
        "depends": [],
        "files": [
          "/usr/bin/iperf3"
        ]
      }
    ],
    "removed": [],
    "changed": []
  },
  "configs": [
    {
      "config": "dhcp",
      "first_boot": false,
      "changes": [
        {
          "key": "dhcp.@dnsmasq[0]",
          "image": "dnsmasq",
          "router": null
        },
        {
          "key": "dhcp.@dnsmasq[0].domainneeded",
          "image": "1",
          "router": null
        },
        {
          "key": "dhcp.@dnsmasq[0].local",
          "image": "/lan/",
          "router": null
        },
        {
          "key": "dhcp.@dnsmasq[0].server",
          "image": "/bench/192.168.1.1 8.8.8.8",
          "router": null
        },
        {
          "key": "dhcp.@host[0]",
          "image": "host",
          "router": null
        },
        {
          "key": "dhcp.@host[0].ip",
          "image": "192.168.1.30",
          "router": null
        },
        {
          "key": "dhcp.@host[0].mac",
          "image": "f4:12:fa:f3:57:68",
          "router": null
        },
        {
          "key": "dhcp.@host[0].name",
          "image": "panel",
          "router": null
        },
        {
          "key": "dhcp.cfg01411c",
          "image": null,
          "router": "dnsmasq"
        },
        {
          "key": "dhcp.cfg01411c.authoritative",
          "image": null,
          "router": "1"
        },
        {
          "key": "dhcp.cfg01411c.boguspriv",
          "image": null,
          "router": "1"
        },
        {
          "key": "dhcp.cfg01411c.cachesize",
          "image": null,
          "router": "1000"
        },
        {
          "key": "dhcp.cfg01411c.domain",
          "image": null,
          "router": "lan"
        },
        {
          "key": "dhcp.cfg01411c.domainneeded",
          "image": null,
          "router": "1"
        },
        {
          "key": "dhcp.cfg01411c.ednspacket_max",
          "image": null,
          "router": "1232"
        },
        {
          "key": "dhcp.cfg01411c.expandhosts",
          "image": null,
          "router": "1"
        },
        {
          "key": "dhcp.cfg01411c.filter_a",
          "image": null,
          "router": "0"
        },
        {
          "key": "dhcp.cfg01411c.filter_aaaa",
          "image": null,
          "router": "0"
        },
        {
          "key": "dhcp.cfg01411c.filterwin2k",
          "image": null,
          "router": "0"
        },
        {
          "key": "dhcp.cfg01411c.leasefile",
          "image": null,
          "router": "/tmp/dhcp.leases"
        },
        {
          "key": "dhcp.cfg01411c.local",
          "image": null,
          "router": "/lan/"
        },
        {
          "key": "dhcp.cfg01411c.localise_queries",
          "image": null,
          "router": "1"
        },
        {
          "key": "dhcp.cfg01411c.localservice",
          "image": null,
          "router": "1"
        },
        {
          "key": "dhcp.cfg01411c.nonegcache",
          "image": null,
          "router": "0"
        },
        {
          "key": "dhcp.cfg01411c.nonwildcard",
          "image": null,
          "router": "1"
        },
        {
          "key": "dhcp.cfg01411c.readethers",
          "image": null,
          "router": "1"
        },
        {
          "key": "dhcp.cfg01411c.rebind_localhost",
          "image": null,
          "router": "1"
        },
        {
          "key": "dhcp.cfg01411c.rebind_protection",
          "image": null,
          "router": "1"
        },
        {
          "key": "dhcp.cfg01411c.resolvfile",
          "image": null,
          "router": "/tmp/resolv.conf.d/resolv.conf.auto"
        },
        {
          "key": "dhcp.cfg0e0a1b",
          "image": null,
          "router": "host"
        },
        {
          "key": "dhcp.cfg0e0a1b.ip",
          "image": null,
          "router": "192.168.1.30"
        },
        {
          "key": "dhcp.cfg0e0a1b.mac",
          "image": null,
          "router": "f4:12:fa:f3:57:68"
        },
        {
          "key": "dhcp.cfg0e0a1b.name",
          "image": null,
          "router": "panel"
        },
        {
          "key": "dhcp.lan.dhcpv4",
          "image": null,
          "router": "server"
        },
        {
          "key": "dhcp.lan.dhcpv6",
          "image": null,
          "router": "disabled"
        },
        {
          "key": "dhcp.lan.ignore",
          "image": "1",
          "router": null
        },
        {
          "key": "dhcp.lan.leasetime",
          "image": null,
          "router": "12h"
        },
        {
          "key": "dhcp.lan.limit",
          "image": null,
          "router": "150"
        },
        {
          "key": "dhcp.lan.ra",
          "image": null,
          "router": "disabled"
        },
        {
          "key": "dhcp.lan.ra_flags",
          "image": null,
          "router": "managed-config other-config"
        },
        {
          "key": "dhcp.lan.ra_slaac",
          "image": null,
          "router": "1"
        },
        {
          "key": "dhcp.lan.start",
          "image": null,
          "router": "100"
        },
        {
          "key": "dhcp.odhcpd",
          "image": null,
          "router": "odhcpd"
        },
        {
          "key": "dhcp.odhcpd.hostsdir",
          "image": null,
          "router": "/tmp/hosts"
        },
        {
          "key": "dhcp.odhcpd.leasefile",
          "image": null,
          "router": "/tmp/odhcpd.leases"
        },
        {
          "key": "dhcp.odhcpd.leasetrigger",
          "image": null,
          "router": "/usr/sbin/odhcpd-update"
        },
        {
          "key": "dhcp.odhcpd.loglevel",
          "image": null,
          "router": "4"
        },
        {
          "key": "dhcp.odhcpd.maindhcp",
          "image": null,
          "router": "0"
        },
        {
          "key": "dhcp.odhcpd.piodir",
          "image": null,
          "router": "/tmp/odhcpd-piodir"
        },
        {
          "key": "dhcp.wan",
          "image": null,
          "router": "dhcp"
        },
        {
          "key": "dhcp.wan.ignore",
          "image": null,
          "router": "1"
        },
        {
          "key": "dhcp.wan.interface",
          "image": null,
          "router": "wan"
        }
      ]
    },
    {
      "config": "dropbear",
      "first_boot": false,
      "changes": [
        {
          "key": "dropbear.@dropbear[0].Port",
          "image": "22",
          "router": "2222"
        }
      ]
    },
    {
      "config": "firewall",
      "first_boot": true,
      "changes": []
    },
    {
      "config": "network",
      "first_boot": true,
      "changes": []
    },
    {
      "config": "wireless",
      "first_boot": true,
      "changes": []
    }
  ],
  "kept_on_flash": [
    "/etc/config/dropbear"
  ],
  "kept_known": true,
  "custom": [
    {
      "package": "dwr921-diag",
      "version": "2",
      "description": "Opt-in, bounded diagnostics for the DWR-921 BM806C modem. The installed helpers send only read-only AT and QMI queries and never start a data session or change modem state.",
      "source": "image",
      "programs": [
        {
          "path": "/usr/bin/dwr921-at-probe",
          "usage": "Usage: dwr921-at-probe [tty-device ...]",
          "source": "custom",
          "has_card": false
        },
        {
          "path": "/usr/bin/dwr921-qmi-readonly",
          "usage": "Usage: dwr921-qmi-readonly [/dev/cdc-wdmN]",
          "source": "custom",
          "has_card": false
        }
      ],
      "card": null,
      "service": null
    },
    {
      "package": "dwr921-internet-led",
      "version": "4",
      "description": "Drives the DWR-921 C3 U-Boot Internet LED when IPv4 reachability is available through LTE or wired WAN.",
      "source": "image",
      "programs": [
        {
          "path": "/usr/sbin/dwr921-internet-led",
          "usage": null,
          "source": "custom",
          "has_card": false
        }
      ],
      "card": null,
      "service": "dwr921-internet-led"
    },
    {
      "package": "dwr921-portctl",
      "version": "2",
      "description": "Safe label-based enable/disable/status operations for the five external PHYs exposed by the DWR-921 C3 U-Boot swconfig switch.",
      "source": "image",
      "programs": [
        {
          "path": "/usr/sbin/dwr921-portctl",
          "usage": "Usage: dwr921-portctl {port-status|port-enable|port-disable} {lan1|lan2|lan3|lan4|wan}",
          "source": "custom",
          "has_card": false
        }
      ],
      "card": "ports",
      "service": null
    }
  ],
  "programs": [
    {
      "path": "/usr/sbin/wifi-mirror",
      "usage": "Usage: wifi-mirror {start|stop|status}",
      "source": "overlay",
      "has_card": false
    }
  ],
  "services": [
    {
      "name": "dwr921-internet-led",
      "source": "custom",
      "package": "dwr921-internet-led",
      "running": true,
      "enabled": true
    },
    {
      "name": "wifi-mirror",
      "source": "overlay",
      "package": null,
      "running": true,
      "enabled": true
    }
  ],
  "capabilities": [
    {
      "name": "Switch",
      "state": "in image",
      "reason": null
    },
    {
      "name": "LTE",
      "state": "missing",
      "reason": "needs uqmi"
    },
    {
      "name": "Capture",
      "state": "in image",
      "reason": null
    },
    {
      "name": "netem",
      "state": "in image",
      "reason": null
    },
    {
      "name": "Firewall",
      "state": "missing",
      "reason": "needs fw4"
    },
    {
      "name": "Monitor mode",
      "state": "missing",
      "reason": "needs iw"
    },
    {
      "name": "Throughput",
      "state": "added after flashing",
      "reason": null
    },
    {
      "name": "Traffic generator",
      "state": "missing",
      "reason": "needs socat"
    },
    {
      "name": "Connections",
      "state": "missing",
      "reason": "needs conntrack"
    }
  ]
}
export const AP2_FIRMWARE: FirmwareCheck = {
  "matches": true,
  "detail": "The firmware matches mini-r35692.bin",
  "image_sha256": "791eac288540dcc76685e226bfbd9fba5318fc9bbdfe1827f83ee455dde09983",
  "router_sha256": "791eac288540dcc76685e226bfbd9fba5318fc9bbdfe1827f83ee455dde09983",
  "read_s": 0.0
}
export const AP2_CHECKLIST: ChecklistInfo = {
  "stamp": "20261108-115158",
  "saved_at": "2026-11-08T11:51:58.970032",
  "profile": {
    "board": "dlink,dwr-921-c3-uboot",
    "revision": "r35692-b8bffeefdf",
    "sha256": "4ede1b92baa19361c0b8bde87dbee473de75a9409351f24104b415bce32fcec0"
  },
  "lost": [
    "/etc/owg/nft/inet-owg_test.nft",
    "/root/notes.txt"
  ],
  "restorable": [
    "/etc/owg/nft/inet-owg_test.nft",
    "/root/notes.txt"
  ],
  "packages_added": []
}
export const COPY_PLAN: NetPlan = {
  "router_id": "ap1",
  "screen": "Discovery",
  "lines": [
    "mkdir -p /root && cat > /root/notes.txt  # stdin: ap2:/root/notes.txt (12 B, sha256 293dea8a158f)",
    "chmod 0644 /root/notes.txt",
    "sha256sum /root/notes.txt"
  ],
  "warnings": [],
  "rollback": false,
  "target_host": null,
  "digest": "64b66c1e74ec91fd"
}
export const HELP_PLAN: NetPlan = {
  "router_id": "ap1",
  "screen": "Discovery",
  "lines": [
    "timeout 5 /usr/sbin/wifi-mirror --help 2>&1 | head -c 8192"
  ],
  "warnings": [
    "wifi-mirror runs on AP1 · bench for at most 5 s. A program that does not know --help may do something else."
  ],
  "rollback": false,
  "target_host": null,
  "digest": "130101ae169ff236"
}
export const PORTCTL_CARD: ToolCard = {
  "board": "dlink,dwr-921-c3-uboot",
  "path": "/usr/sbin/dwr921-portctl",
  "name": "dwr921-portctl",
  "commands": [
    {
      "label": "port-status",
      "args": [
        "port-status",
        "{arg1}"
      ],
      "params": [
        {
          "name": "arg1",
          "kind": "choice",
          "choices": [
            "lan1",
            "lan2",
            "lan3",
            "lan4",
            "wan"
          ],
          "pattern": null,
          "minimum": null,
          "maximum": null
        }
      ],
      "write": true
    },
    {
      "label": "port-enable",
      "args": [
        "port-enable",
        "{arg1}"
      ],
      "params": [
        {
          "name": "arg1",
          "kind": "choice",
          "choices": [
            "lan1",
            "lan2",
            "lan3",
            "lan4",
            "wan"
          ],
          "pattern": null,
          "minimum": null,
          "maximum": null
        }
      ],
      "write": true
    },
    {
      "label": "port-disable",
      "args": [
        "port-disable",
        "{arg1}"
      ],
      "params": [
        {
          "name": "arg1",
          "kind": "choice",
          "choices": [
            "lan1",
            "lan2",
            "lan3",
            "lan4",
            "wan"
          ],
          "pattern": null,
          "minimum": null,
          "maximum": null
        }
      ],
      "write": true
    }
  ]
}
export const FLASH_PLAN: FlashPlanOut = {
  "lines": [
    "mkdir -p /tmp/owg",
    "cat > /tmp/owg/fw-06988f7bb216.bin  # stdin: mini-r35700.bin (65840 B, sha256 06988f7bb216)",
    "sha256sum /tmp/owg/fw-06988f7bb216.bin",
    "ubus call system validate_firmware_image '{\"path\":\"/tmp/owg/fw-06988f7bb216.bin\"}'",
    "sysupgrade -T /tmp/owg/fw-06988f7bb216.bin",
    "grep -qx /etc/owg/ /etc/sysupgrade.conf || echo /etc/owg/ >> /etc/sysupgrade.conf",
    "mkdir -p /tmp/owg && start-stop-daemon -S -b -m -p /tmp/owg/flash.pid -x /bin/sh -- -c 'sleep 2; sysupgrade /tmp/owg/fw-06988f7bb216.bin; rm -f /tmp/owg/flash.*'"
  ],
  "warnings": [
    "AP2 \u00b7 office reboots and is off the network for about 3 minutes. Once sysupgrade starts it cannot be stopped."
  ],
  "digest": "a7e5f642ff010ae2"
}
