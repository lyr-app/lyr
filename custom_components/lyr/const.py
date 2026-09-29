"""Constants for the Lyr integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "lyr"

DEFAULT_PORT: Final = 3000
CONF_TOKEN: Final = "token"

# The Core caches its zone snapshot for 2 s and reads LMS sequentially, so a
# poll every 10 s costs one sweep per 10 s whatever else is polling. Commands
# issued from Home Assistant refresh immediately.
SCAN_INTERVAL: Final = timedelta(seconds=10)

# Browse lists are capped: a library holds thousands of artists and HA's media
# browser has no paging.
BROWSE_LIMIT: Final = 300

SERVICE_PLAY_PROMPT: Final = "play_prompt"
SERVICE_START_RADIO: Final = "start_radio"
SERVICE_PLAY_SEARCH: Final = "play_search"

ATTR_PROMPT: Final = "prompt"
ATTR_ARTIST: Final = "artist"
ATTR_QUERY: Final = "query"
ATTR_KIND: Final = "kind"
ATTR_SHUFFLE: Final = "shuffle"

# Library item kinds `POST /api/shortcuts/play-item` accepts.
ITEM_KINDS: Final = ("playlist", "album", "artist", "track", "genre")
