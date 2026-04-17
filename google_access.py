"""
JARVIS Google Access — Gmail and Google Calendar support.

Uses OAuth client credentials + refresh token stored in .env.
If Google credentials are missing, callers should fall back to AppleScript.
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any

import httpx

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1"
GOOGLE_CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"
GOOGLE_SCOPES_GMAIL = "https://www.googleapis.com/auth/gmail.modify"
GOOGLE_SCOPES_CALENDAR = "https://www.googleapis.com/auth/calendar.readonly"

_token_cache: dict[str, Any] = {"access_token": "", "expires_at": 0.0, "auth_failed": False}


def is_google_configured() -> bool:
    return all(
        os.getenv(key, "").strip()
        for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")
    )


def is_google_usable() -> bool:
    return is_google_configured() and not bool(_token_cache.get("auth_failed"))


def _calendar_ids() -> list[str]:
    raw = os.getenv("GOOGLE_CALENDAR_IDS", "").strip()
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return ["primary"]


def _calendar_label(calendar_id: str) -> str:
    user_email = os.getenv("GOOGLE_USER_EMAIL", "").strip()
    if calendar_id == "primary":
        return user_email or "Google Calendar"
    return calendar_id


async def _refresh_access_token() -> str | None:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN", "").strip()
    if not (client_id and client_secret and refresh_token):
        return None

    now = time.time()
    cached_token = str(_token_cache.get("access_token", ""))
    expires_at = float(_token_cache.get("expires_at", 0.0))
    if cached_token and expires_at > now + 60:
        return cached_token

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data=data)
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        _token_cache["auth_failed"] = True
        detail = resp.text[:300].replace("\n", " ").strip()
        log = __import__("logging").getLogger("jarvis.google")
        log.warning(f"Google token refresh failed: {resp.status_code} {detail}")
        raise e
    payload = resp.json()
    access_token = payload.get("access_token")
    if not access_token:
        return None

    expires_in = int(payload.get("expires_in", 3600))
    _token_cache["access_token"] = access_token
    _token_cache["expires_at"] = now + expires_in
    return access_token


async def _google_request(method: str, url: str, *, params: dict[str, Any] | None = None, json: Any = None) -> dict[str, Any]:
    token = await _refresh_access_token()
    if not token:
        raise RuntimeError("Google credentials are not configured")

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.request(method, url, params=params, json=json, headers=headers)
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        detail = resp.text[:300].replace("\n", " ").strip()
        log = __import__("logging").getLogger("jarvis.google")
        log.warning(f"Google request failed: {resp.status_code} {detail}")
        raise e
    return resp.json()


async def google_unread_count() -> dict[str, Any]:
    """Return Gmail unread count for the configured Google account."""
    inbox = await _google_request("GET", f"{GOOGLE_GMAIL_BASE}/users/me/labels/INBOX")
    total = int(inbox.get("messagesUnread", 0) or 0)
    label = _calendar_label("primary")
    return {"total": total, "accounts": {label: total} if label else {"Google": total}}


async def google_recent_messages(count: int = 10) -> list[dict]:
    """Return recent Gmail inbox messages."""
    listing = await _google_request(
        "GET",
        f"{GOOGLE_GMAIL_BASE}/users/me/messages",
        params={"maxResults": count, "labelIds": "INBOX", "includeSpamTrash": "false"},
    )
    msgs = listing.get("messages", [])
    if not msgs:
        return []

    results: list[dict] = []
    for item in msgs[:count]:
        msg = await _google_request(
            "GET",
            f"{GOOGLE_GMAIL_BASE}/users/me/messages/{item['id']}",
            params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
        )
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        results.append(
            {
                "sender": headers.get("from", "Unknown sender"),
                "subject": headers.get("subject", "(no subject)"),
                "date": headers.get("date", ""),
                "read": "UNREAD" not in msg.get("labelIds", []),
                "preview": msg.get("snippet", ""),
            }
        )
    return results


def _extract_gmail_body(payload: dict[str, Any]) -> str:
    """Extract readable text from a Gmail message payload."""
    if not payload:
        return ""

    body = payload.get("body", {}) or {}
    data = body.get("data")
    if data:
        try:
            padded = data + "=" * (-len(data) % 4)
            return base64.urlsafe_b64decode(padded.encode()).decode("utf-8", errors="ignore").strip()
        except Exception:
            pass

    for part in payload.get("parts", []) or []:
        mime = (part.get("mimeType") or "").lower()
        if mime == "text/plain":
            text = _extract_gmail_body(part)
            if text:
                return text

    for part in payload.get("parts", []) or []:
        text = _extract_gmail_body(part)
        if text:
            return text

    return ""


async def google_unread_messages(count: int = 10) -> list[dict]:
    """Return unread Gmail inbox messages."""
    listing = await _google_request(
        "GET",
        f"{GOOGLE_GMAIL_BASE}/users/me/messages",
        params={"maxResults": count, "q": "in:inbox is:unread", "includeSpamTrash": "false"},
    )
    msgs = listing.get("messages", [])
    if not msgs:
        return []

    results: list[dict] = []
    for item in msgs[:count]:
        msg = await _google_request(
            "GET",
            f"{GOOGLE_GMAIL_BASE}/users/me/messages/{item['id']}",
            params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
        )
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        results.append(
            {
                "sender": headers.get("from", "Unknown sender"),
                "subject": headers.get("subject", "(no subject)"),
                "date": headers.get("date", ""),
                "read": False,
                "preview": msg.get("snippet", ""),
            }
        )
    return results


async def google_latest_message() -> dict | None:
    """Return the newest inbox message with full body text."""
    listing = await _google_request(
        "GET",
        f"{GOOGLE_GMAIL_BASE}/users/me/messages",
        params={"maxResults": 1, "labelIds": "INBOX", "includeSpamTrash": "false"},
    )
    msgs = listing.get("messages", [])
    if not msgs:
        return None

    msg = await _google_request(
        "GET",
        f"{GOOGLE_GMAIL_BASE}/users/me/messages/{msgs[0]['id']}",
        params={"format": "full"},
    )
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    body = _extract_gmail_body(msg.get("payload", {}) or {})
    return {
        "id": msg.get("id", ""),
        "sender": headers.get("from", "Unknown sender"),
        "subject": headers.get("subject", "(no subject)"),
        "date": headers.get("date", ""),
        "read": "UNREAD" not in msg.get("labelIds", []),
        "content": body or msg.get("snippet", ""),
        "snippet": msg.get("snippet", ""),
    }


async def google_search_messages(query: str, count: int = 10) -> list[dict]:
    listing = await _google_request(
        "GET",
        f"{GOOGLE_GMAIL_BASE}/users/me/messages",
        params={"maxResults": count, "q": query, "includeSpamTrash": "false"},
    )
    msgs = listing.get("messages", [])
    if not msgs:
        return []

    results: list[dict] = []
    for item in msgs[:count]:
        msg = await _google_request(
            "GET",
            f"{GOOGLE_GMAIL_BASE}/users/me/messages/{item['id']}",
            params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
        )
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        results.append(
            {
                "sender": headers.get("from", "Unknown sender"),
                "subject": headers.get("subject", "(no subject)"),
                "date": headers.get("date", ""),
                "read": "UNREAD" not in msg.get("labelIds", []),
                "preview": msg.get("snippet", ""),
            }
        )
    return results


async def google_read_message(subject_match: str) -> dict | None:
    listing = await _google_request(
        "GET",
        f"{GOOGLE_GMAIL_BASE}/users/me/messages",
        params={"maxResults": 10, "q": f"subject:{subject_match}", "includeSpamTrash": "false"},
    )
    msgs = listing.get("messages", [])
    if not msgs:
        return None

    msg = await _google_request(
        "GET",
        f"{GOOGLE_GMAIL_BASE}/users/me/messages/{msgs[0]['id']}",
        params={"format": "full"},
    )
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    return {
        "sender": headers.get("from", "Unknown sender"),
        "subject": headers.get("subject", "(no subject)"),
        "date": headers.get("date", ""),
        "content": _extract_gmail_body(msg.get("payload", {}) or {}) or msg.get("snippet", ""),
    }


async def google_send_message(to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> dict[str, Any]:
    """Send an email using Gmail."""
    lines = [f"To: {to}", f"Subject: {subject}", "Content-Type: text/plain; charset=\"UTF-8\""]
    if cc.strip():
        lines.insert(1, f"Cc: {cc}")
    if bcc.strip():
        lines.insert(1, f"Bcc: {bcc}")
    raw_message = "\r\n".join(lines) + "\r\n\r\n" + body
    encoded = base64.urlsafe_b64encode(raw_message.encode("utf-8")).decode("utf-8").rstrip("=")
    return await _google_request(
        "POST",
        f"{GOOGLE_GMAIL_BASE}/users/me/messages/send",
        json={"raw": encoded},
    )


async def google_modify_message(message_id: str, *, add_labels: list[str] | None = None, remove_labels: list[str] | None = None) -> dict[str, Any]:
    """Add/remove Gmail labels on a message."""
    payload: dict[str, Any] = {}
    if add_labels:
        payload["addLabelIds"] = add_labels
    if remove_labels:
        payload["removeLabelIds"] = remove_labels
    return await _google_request(
        "POST",
        f"{GOOGLE_GMAIL_BASE}/users/me/messages/{message_id}/modify",
        json=payload,
    )


async def google_mark_message_read(message_id: str) -> dict[str, Any]:
    return await google_modify_message(message_id, remove_labels=["UNREAD"])


async def google_mark_message_unread(message_id: str) -> dict[str, Any]:
    return await google_modify_message(message_id, add_labels=["UNREAD"])


async def google_archive_message(message_id: str) -> dict[str, Any]:
    return await google_modify_message(message_id, remove_labels=["INBOX"])


async def google_trash_message(message_id: str) -> dict[str, Any]:
    return await _google_request(
        "POST",
        f"{GOOGLE_GMAIL_BASE}/users/me/messages/{message_id}/trash",
        json={},
    )


async def google_todays_events() -> list[dict]:
    tz_name = os.getenv("GOOGLE_TIMEZONE", "").strip()
    try:
        tz = ZoneInfo(tz_name) if tz_name else (datetime.now().astimezone().tzinfo or timezone.utc)
    except Exception:
        tz = datetime.now().astimezone().tzinfo or timezone.utc
    now = datetime.now(tz=tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    events: list[dict] = []
    for calendar_id in _calendar_ids():
        payload = await _google_request(
            "GET",
            f"{GOOGLE_CALENDAR_BASE}/calendars/{calendar_id}/events",
            params={
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 50,
            },
        )
        for item in payload.get("items", []):
            start_info = item.get("start", {})
            if "dateTime" in start_info:
                parsed = datetime.fromisoformat(start_info["dateTime"].replace("Z", "+00:00"))
                start_label = parsed.astimezone(tz).strftime("%-I:%M %p")
                all_day = False
                start_dt = parsed.astimezone(tz)
            else:
                start_label = "ALL_DAY"
                all_day = True
                start_dt = None
            events.append(
                {
                    "calendar": _calendar_label(calendar_id),
                    "title": item.get("summary", "(No title)"),
                    "start": start_label,
                    "start_dt": start_dt,
                    "all_day": all_day,
                }
            )

    events.sort(key=lambda e: (not e["all_day"], e.get("start_dt") or datetime.max.replace(tzinfo=tz)))
    return events
