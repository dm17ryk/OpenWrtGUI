"""One job at a time per router or radio: the error every "busy" refusal shares (409)."""

from __future__ import annotations


class RouterBusy(Exception):
    """Another job holds the router or the radio (409)."""
