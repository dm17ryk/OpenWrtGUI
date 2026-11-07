"""The Firewall screen's reads, as exact command strings (recorded from AP2 and replayed by the tests)."""

from __future__ import annotations

UCI_FIREWALL = "uci -X show firewall"
NFT_JSON = "nft -j list ruleset"
NFT_TEXT = "nft -a list ruleset"
CUSTOM_FILES = 'for f in /etc/nftables.d/*.nft; do [ -e "$f" ] && { echo "=== $f"; cat "$f"; }; done'
ROM_CUSTOM = "ls /rom/etc/nftables.d"
TC_QDISCS = "tc qdisc show"
FW4_PRINT = "fw4 print"

FIREWALL_READS = (UCI_FIREWALL, NFT_JSON, NFT_TEXT, CUSTOM_FILES, ROM_CUSTOM, TC_QDISCS)
