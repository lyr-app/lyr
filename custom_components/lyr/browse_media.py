"""Browse the Lyr library from Home Assistant's media browser.

Content ids are `lyr:<kind>:<id>`. The id part may itself contain colons (a
TIDAL playlist id is an Airable URL), so it is split once from the left.
Everything is read from the Core's own library routes — the same rows the app
shows, with Lyr's hidden/withdrawn rules already applied — so no request goes
to Qobuz or TIDAL from here.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import BrowseError, BrowseMedia, MediaClass, MediaType

from .api import LyrClient
from .const import BROWSE_LIMIT

PREFIX = "lyr"
ROOT_ID = f"{PREFIX}:root"

DIRECTORIES: dict[str, tuple[str, MediaClass]] = {
    "playlists": ("Playlists", MediaClass.PLAYLIST),
    "albums": ("Recently added albums", MediaClass.ALBUM),
    "artists": ("Artists", MediaClass.ARTIST),
    "genres": ("Genres", MediaClass.GENRE),
}

KIND_CLASS: dict[str, tuple[MediaClass, str]] = {
    "playlist": (MediaClass.PLAYLIST, MediaType.PLAYLIST),
    "album": (MediaClass.ALBUM, MediaType.ALBUM),
    "artist": (MediaClass.ARTIST, MediaType.ARTIST),
    "genre": (MediaClass.GENRE, MediaType.GENRE),
    "track": (MediaClass.TRACK, MediaType.TRACK),
}


def make_id(kind: str, item_id: str) -> str:
    return f"{PREFIX}:{kind}:{item_id}"


def parse_id(content_id: str) -> tuple[str, str] | None:
    """`lyr:album:28714` → ("album", "28714"); None when it is not ours."""
    parts = str(content_id or "").split(":", 2)
    if len(parts) != 3 or parts[0] != PREFIX or not parts[2]:
        return None
    return parts[1], parts[2]


def is_lyr_id(content_id: str) -> bool:
    return str(content_id or "").startswith(f"{PREFIX}:")


def _item(
    client: LyrClient,
    kind: str,
    item_id: str,
    title: str,
    artwork: str | None,
    *,
    can_expand: bool = True,
    can_play: bool = True,
) -> BrowseMedia:
    media_class, media_type = KIND_CLASS[kind]
    return BrowseMedia(
        title=title or item_id,
        media_class=media_class,
        media_content_id=make_id(kind, item_id),
        media_content_type=media_type,
        can_play=can_play,
        can_expand=can_expand,
        thumbnail=client.artwork_url(artwork),
    )


def _directory(key: str, children: list[BrowseMedia] | None = None) -> BrowseMedia:
    title, child_class = DIRECTORIES[key]
    return BrowseMedia(
        title=title,
        media_class=MediaClass.DIRECTORY,
        media_content_id=make_id("dir", key),
        media_content_type="library",
        children_media_class=child_class,
        can_play=False,
        can_expand=True,
        children=children,
    )


def root_node(extra_children: list[BrowseMedia] | None = None) -> BrowseMedia:
    children = [_directory(key) for key in DIRECTORIES]
    children.extend(extra_children or [])
    return BrowseMedia(
        title="Lyr",
        media_class=MediaClass.DIRECTORY,
        media_content_id=ROOT_ID,
        media_content_type="library",
        children_media_class=MediaClass.DIRECTORY,
        can_play=False,
        can_expand=True,
        children=children,
    )


def _track_children(client: LyrClient, rows: list[dict[str, Any]], playable: bool) -> list[BrowseMedia]:
    out: list[BrowseMedia] = []
    for r in rows:
        key = str(r.get("key") or r.get("externalId") or "")
        title = str(r.get("title") or "")
        artist = str(r.get("artistName") or r.get("artist") or "")
        label = f"{title} — {artist}" if artist else title
        out.append(
            _item(
                client,
                "track",
                key or title,
                label,
                r.get("artworkUrl") or r.get("artwork_url"),
                can_expand=False,
                # A playlist row is not always a library track, and play-item
                # plays tracks by library key; play the playlist instead.
                can_play=playable and bool(key),
            )
        )
    return out


async def async_browse(client: LyrClient, content_id: str) -> BrowseMedia:
    """The node for `content_id`, with its children."""
    if content_id in (None, "", ROOT_ID):
        return root_node()
    parsed = parse_id(content_id)
    if not parsed:
        raise BrowseError(f"Unknown media id: {content_id}")
    kind, item_id = parsed

    if kind == "dir":
        if item_id == "playlists":
            rows = await client.playlists(BROWSE_LIMIT)
            children = [
                _item(client, "playlist", str(r.get("id")), str(r.get("name") or ""), r.get("artworkUrl"))
                for r in rows
                if r.get("id")
            ]
        elif item_id == "albums":
            rows = await client.albums(BROWSE_LIMIT, sort="added_desc")
            children = [
                _item(
                    client,
                    "album",
                    str(r.get("externalId")),
                    f"{r.get('title') or ''} — {r.get('artistName') or ''}".strip(" —"),
                    r.get("artworkUrl"),
                )
                for r in rows
                if r.get("externalId")
            ]
        elif item_id == "artists":
            rows = await client.artists(BROWSE_LIMIT)
            children = [
                _item(
                    client,
                    "artist",
                    str(r.get("name")),
                    str(r.get("name")),
                    r.get("artworkUrl") or r.get("fallbackArtworkUrl"),
                )
                for r in rows
                if r.get("name")
            ]
        elif item_id == "genres":
            rows = await client.genres()
            children = [
                _item(client, "genre", str(r.get("slug")), str(r.get("name") or r.get("slug")), r.get("imageUrl"))
                for r in rows
                if r.get("slug")
            ]
        else:
            raise BrowseError(f"Unknown directory: {item_id}")
        return _directory(item_id, children)

    if kind == "playlist":
        rows = await client.playlist_tracks(item_id, BROWSE_LIMIT)
        node = _item(client, "playlist", item_id, "Playlist", None)
        node.children = _track_children(client, rows, playable=False)
        node.children_media_class = MediaClass.TRACK
        return node
    if kind == "album":
        rows = await client.album_tracks(item_id, 500)
        rows.sort(key=lambda r: (int(r.get("discNumber") or 1), int(r.get("trackNumber") or 0)))
        title = str(rows[0].get("albumTitle") or "Album") if rows else "Album"
        node = _item(client, "album", item_id, title, rows[0].get("artworkUrl") if rows else None)
        node.children = _track_children(client, rows, playable=True)
        node.children_media_class = MediaClass.TRACK
        return node
    if kind == "artist":
        rows = await client.albums(BROWSE_LIMIT, artistName=item_id)
        node = _item(client, "artist", item_id, item_id, None)
        node.children = [
            _item(client, "album", str(r.get("externalId")), str(r.get("title") or ""), r.get("artworkUrl"))
            for r in rows
            if r.get("externalId")
        ]
        node.children_media_class = MediaClass.ALBUM
        return node
    if kind == "genre":
        rows = await client.albums(BROWSE_LIMIT, genre=item_id)
        node = _item(client, "genre", item_id, item_id, None)
        node.children = [
            _item(
                client,
                "album",
                str(r.get("externalId")),
                f"{r.get('title') or ''} — {r.get('artistName') or ''}".strip(" —"),
                r.get("artworkUrl"),
            )
            for r in rows
            if r.get("externalId")
        ]
        node.children_media_class = MediaClass.ALBUM
        return node
    raise BrowseError(f"Cannot browse {kind}")


def search_results(client: LyrClient, items: list[dict[str, Any]]) -> list[BrowseMedia]:
    """`/api/shortcuts/resolve` rows as browse items, best match first."""
    out: list[BrowseMedia] = []
    for it in items:
        kind = str(it.get("kind") or "")
        if kind not in KIND_CLASS or not it.get("id"):
            continue
        title = str(it.get("title") or "")
        subtitle = str(it.get("subtitle") or "")
        out.append(
            _item(
                client,
                kind,
                str(it["id"]),
                f"{title} — {subtitle}" if subtitle and kind in ("album", "track") else title,
                it.get("artworkUrl"),
                can_expand=kind != "track",
            )
        )
    return out
