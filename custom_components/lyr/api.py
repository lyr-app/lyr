"""A small async client for the Lyr Core's HTTP API.

Only routes the Lyr apps already use, plus the zone routes added for this
integration (`server/zones-routes.ts`). The Core is the only thing this talks
to: Lyr Server (LMS), Qobuz, TIDAL and SoundCloud are all reached through it.
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

import aiohttp

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)


class LyrError(Exception):
    """Base error."""


class LyrConnectionError(LyrError):
    """The Core could not be reached."""


class LyrApiError(LyrError):
    """The Core answered with an error."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


class LyrClient:
    """Talks to one Lyr Core."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        token: str | None = None,
    ) -> None:
        self._session = session
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self._headers = {"X-Lyr-Controller": "home-assistant"}
        if token:
            self._headers["X-Lyr-Token"] = token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        timeout: aiohttp.ClientTimeout = REQUEST_TIMEOUT,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with self._session.request(
                method,
                url,
                params=params,
                json=json,
                headers=self._headers,
                timeout=timeout,
            ) as resp:
                try:
                    data = await resp.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError):
                    data = None
                if resp.status >= 400:
                    message = ""
                    if isinstance(data, dict):
                        message = str(data.get("error") or "")
                    raise LyrApiError(resp.status, message or resp.reason or "error")
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise LyrConnectionError(f"{url}: {err}") from err

    # -- identity and state ------------------------------------------------

    async def status(self) -> dict[str, Any]:
        """`GET /api/status` — name, and the Lyr Server it drives."""
        return await self._request("GET", "/api/status")

    async def identity(self) -> dict[str, Any]:
        """`GET /api/core/identity` — `coreId`, stable for the life of the Core."""
        return await self._request("GET", "/api/core/identity")

    async def zones(self) -> dict[str, Any]:
        """`GET /api/zones/now-playing` — every zone in one call."""
        return await self._request("GET", "/api/zones/now-playing")

    # -- zone control ------------------------------------------------------

    async def command(self, player_id: str, action: str, **args: Any) -> dict[str, Any]:
        """`POST /api/zones/<id>/command`."""
        return await self._request(
            "POST",
            f"/api/zones/{quote(player_id)}/command",
            json={"action": action, **args},
        )

    async def play_item(
        self, player_id: str, kind: str, item_id: str, shuffle: bool = False
    ) -> dict[str, Any]:
        """`POST /api/shortcuts/play-item` — a library item, queued as the app does."""
        return await self._request(
            "POST",
            "/api/shortcuts/play-item",
            json={"playerId": player_id, "kind": kind, "id": item_id, "shuffle": shuffle},
            timeout=aiohttp.ClientTimeout(total=45),
        )

    async def play_prompt(self, player_id: str, prompt: str) -> dict[str, Any]:
        """`POST /api/zones/<id>/play-prompt` — Liora builds and plays it (202)."""
        return await self._request(
            "POST", f"/api/zones/{quote(player_id)}/play-prompt", json={"prompt": prompt}
        )

    async def play_radio(self, player_id: str, artist: str | None = None) -> dict[str, Any]:
        """`POST /api/zones/<id>/play-radio` — artist radio (202)."""
        body: dict[str, Any] = {}
        if artist:
            body["artist"] = artist
        return await self._request(
            "POST", f"/api/zones/{quote(player_id)}/play-radio", json=body
        )

    async def set_explicit_filter(self, active: bool) -> dict[str, Any]:
        """`PATCH /api/user-prefs` — the household-wide explicit filter toggle."""
        return await self._request(
            "PATCH", "/api/user-prefs", json={"settings": {"explicitFilterActive": active}}
        )

    # -- library -----------------------------------------------------------

    async def resolve(self, query: str, kind: str = "any") -> list[dict[str, Any]]:
        """`GET /api/shortcuts/resolve` — library search, best match first."""
        data = await self._request(
            "GET", "/api/shortcuts/resolve", params={"q": query, "type": kind}
        )
        return list((data or {}).get("items") or [])

    async def playlists(self, limit: int) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/library/playlists", params={"limit": limit})
        return list((data or {}).get("items") or [])

    async def playlist_tracks(self, playlist_id: str, limit: int) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            f"/api/library/playlists/{quote(playlist_id, safe='')}/tracks",
            params={"limit": limit},
        )
        return list((data or {}).get("items") or [])

    async def albums(self, limit: int, **filters: str) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, **filters}
        data = await self._request("GET", "/api/library/albums", params=params)
        return list((data or {}).get("items") or [])

    async def album_tracks(self, album_id: str, limit: int) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            "/api/library/tracks",
            params={"albumExternalId": album_id, "limit": limit, "includeIncomplete": 1},
        )
        return list((data or {}).get("items") or [])

    async def artists(self, limit: int) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/library/artists", params={"limit": limit})
        return list((data or {}).get("items") or [])

    async def genres(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/library/genres")
        return list((data or {}).get("items") or [])

    def artwork_url(self, raw: str | None) -> str | None:
        """An artwork URL a browser can fetch.

        The library stores local-album covers LMS-relative (`/music/<id>/cover.jpg`);
        the Core's image proxy resolves those against its own Lyr Server.
        """
        if not raw:
            return None
        if raw.startswith(("http://", "https://")):
            return raw
        if raw.startswith("data:"):
            return None
        return f"{self.base_url}/api/image-proxy?url={quote(raw, safe='')}&w=300"
