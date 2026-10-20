"""WhatsApp chat export (S-3.7.5, T-3.7.5.1): ``.txt`` or the ``.zip`` with media.

Both phone formats:

- iOS: ``[31/01/24, 9:05:01 PM] Name: text`` (``_chat.txt`` inside a zip).
  System lines and media placeholders are attributed to a sender but start
  with a left-to-right mark (U+200E): ``Name: ‎image omitted``.
- Android: ``31/01/24, 21:05 - Name: text`` (``WhatsApp Chat with Name.txt``).
  System lines have no ``Name:`` part.

Lines that do not start a message continue the previous one. Day-first or
month-first dates are inferred from the whole file (a first field above 12
means day-first; a second above 12 means month-first); when nothing decides
it, the ``date_order`` option does (default day-first) and the preview says
so. Times are the phone's local time; the ``timezone`` option converts them.

Messages are grouped into **turns**: consecutive messages from one sender no
more than ``ECHO_IMPORT_TURN_GAP_MIN`` apart, up to
``ECHO_IMPORT_TURN_MAX_CHARS``. One turn is one share, so authorship is
uniform within a share: the user's turns are their own words
(``author_is_tenant``), everyone else's are context only. With
``redact_other_party`` only the user's turns are stored at all.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings
from app.connectors.archive import ExportUnreadable, ImportPreview, ImportSource, stable_id
from app.connectors.base import ImportedShare

NAME = "whatsapp"
LABEL = "WhatsApp chat"
CONTENT_TYPE = "whatsapp_message"

_MARKS = "‎‏‪‫‬‭‮⁦⁧⁨⁩﻿"
_ODD_SPACES = {" ": " ", " ": " ", " ": " "}
_DATE = r"(?P<date>\d{1,4}[./-]\d{1,2}[./-]\d{1,4})"
_TIME = r"(?P<time>\d{1,2}[:.]\d{2}(?:[:.]\d{2})?(?:\s*[aApP]\.?\s*[mM]\.?)?)"
_IOS = re.compile(rf"^\[{_DATE},?\s+{_TIME}\]\s(?P<rest>.*)$")
_ANDROID = re.compile(rf"^{_DATE},?\s+{_TIME}\s+[-–]\s(?P<rest>.*)$")

_MEDIA = [
    re.compile(r"^<?(image|video|audio|sticker|gif|document|contact card|photo|voice message)\s+omitted>?$", re.I),
    re.compile(r"^<media omitted>$", re.I),
    re.compile(r"^<attached:\s*[^>]+>$", re.I),
    re.compile(r"^\S+\.\w{2,5}\s+\(file attached\)", re.I),
]
_MEDIA_KIND = re.compile(r"(image|photo|video|audio|opus|sticker|gif|document|pdf|contact|voice)", re.I)
_ATTACHED = re.compile(r"\.(?P<ext>\w{2,5})\s+\(file attached\)", re.I)
_EXT_KIND = {
    "jpg": "image", "jpeg": "image", "png": "image", "webp": "sticker", "heic": "image",
    "mp4": "video", "3gp": "video", "mov": "video", "gif": "gif",
    "opus": "audio", "m4a": "audio", "mp3": "audio", "aac": "audio", "ogg": "audio",
    "pdf": "document", "docx": "document", "xlsx": "document", "vcf": "contact",
}
_DELETED = re.compile(r"^(this message was deleted|you deleted this message)\.?$", re.I)
_EDITED = re.compile(r"\s*<this message was edited>\s*$", re.I)
_CHAT_NAME = re.compile(r"^whatsapp chat (?:with|-)\s*(?P<name>.+?)(?:\s*\(\d+\))?$", re.I)
_NO_MARKS = {ord(c): None for c in _MARKS}
_PM = re.compile(r"[pP]\.?\s*[mM]")
_AM = re.compile(r"[aA]\.?\s*[mM]")
_DIGITS = re.compile(r"\d+")
_DATE_SEP = re.compile(r"[./-]")


@dataclass
class _Message:
    when: datetime  # naive, the phone's local time
    sender: str | None
    text: str
    kind: str  # text | media | system | deleted
    media: str | None = None


@dataclass
class _Stats:
    messages: int = 0
    media: int = 0
    system: int = 0
    deleted: int = 0
    participants: dict[str, dict[str, Any]] = field(default_factory=dict)
    first_at: datetime | None = None
    last_at: datetime | None = None


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _chat_member(source: ImportSource) -> str | None:
    if not source.is_zip:
        return None
    txts = [n for n in source.member_names() if n.lower().endswith(".txt")]
    for n in txts:
        if n.rsplit("/", 1)[-1] == "_chat.txt":
            return n
    for n in txts:
        if n.rsplit("/", 1)[-1].lower().startswith("whatsapp chat"):
            return n
    return txts[0] if len(txts) == 1 else None


def sniff(source: ImportSource) -> bool:
    try:
        if source.is_zip:
            member = _chat_member(source)
            if member is None:
                return False
            stream = source.open_text(member)
        elif source.filename.lower().endswith(".txt"):
            stream = source.open_text()
        else:
            return False
        with stream:
            seen = 0
            for line in stream:
                line = _clean(line)
                if not line.strip():
                    continue
                if _IOS.match(line) or _ANDROID.match(line):
                    return True
                seen += 1
                if seen >= 20:
                    return False
    except Exception:
        return False
    return False


def chat_name(source: ImportSource) -> str:
    stem = source.filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem = re.sub(r"\.(txt|zip)$", "", stem, flags=re.I).strip()
    m = _CHAT_NAME.match(stem)
    if m:
        return m.group("name").strip()
    if source.is_zip:
        member = _chat_member(source)
        if member:
            inner = re.sub(r"\.txt$", "", member.rsplit("/", 1)[-1], flags=re.I)
            m = _CHAT_NAME.match(inner)
            if m:
                return m.group("name").strip()
    return stem if stem and stem != "_chat" else "WhatsApp chat"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _clean(line: str) -> str:
    """Strip direction marks before the header and normalise odd spaces, but
    keep a mark at the start of the MESSAGE (it flags iOS system and media)."""
    line = line.rstrip("\r\n")
    for k, v in _ODD_SPACES.items():
        line = line.replace(k, v)
    return line.lstrip(_MARKS)


def _strip_marks(text: str) -> str:
    text = text.translate(_NO_MARKS).strip()
    return text if text.isascii() else unicodedata.normalize("NFC", text)


def _split_date(raw: str) -> tuple[str, str, str]:
    parts = _DATE_SEP.split(raw)
    return parts[0], parts[1], parts[2]


def infer_date_order(source: ImportSource, member: str | None) -> tuple[str, bool]:
    """('dmy' | 'mdy' | 'ymd', decided). Reads the file once, line by line."""
    first_big = second_big = year_first = False
    with source.open_text(member) as stream:
        for line in stream:
            line = _clean(line)
            m = _IOS.match(line) or _ANDROID.match(line)
            if not m:
                continue
            a, b, _ = _split_date(m.group("date"))
            if len(a) == 4:
                year_first = True
                break
            if int(a) > 12:
                first_big = True
            if int(b) > 12:
                second_big = True
            if first_big or second_big:
                break
    if year_first:
        return "ymd", True
    if first_big and not second_big:
        return "dmy", True
    if second_big and not first_big:
        return "mdy", True
    return "dmy", False


def _media_kind(body: str) -> str:
    attached = _ATTACHED.search(body)
    if attached:
        return _EXT_KIND.get(attached.group("ext").lower(), "media")
    kind = _MEDIA_KIND.search(body)
    return kind.group(1).lower() if kind else "media"


def _parse_when(date_raw: str, time_raw: str, order: str) -> datetime | None:
    a, b, c = _split_date(date_raw)
    try:
        if order == "ymd":
            year, month, day = int(a), int(b), int(c)
        elif order == "mdy":
            month, day, year = int(a), int(b), int(c)
        else:
            day, month, year = int(a), int(b), int(c)
        if year < 100:
            year += 2000
        t = time_raw.strip()
        pm = _PM.search(t) is not None
        am = _AM.search(t) is not None
        nums = [int(x) for x in _DIGITS.findall(t)]
        hour, minute = nums[0], nums[1]
        second = nums[2] if len(nums) > 2 else 0
        if pm and hour < 12:
            hour += 12
        if am and hour == 12:
            hour = 0
        return datetime(year, month, day, hour, minute, second)
    except (ValueError, IndexError):
        return None


def _messages(source: ImportSource, member: str | None, order: str) -> Iterator[_Message]:
    current: _Message | None = None
    with source.open_text(member) as stream:
        for raw in stream:
            line = _clean(raw)
            m = _IOS.match(line) or _ANDROID.match(line)
            when = _parse_when(m.group("date"), m.group("time"), order) if m else None
            if m is None or when is None:
                if current is not None and line.strip():
                    current.text = f"{current.text}\n{_strip_marks(line)}" if current.text else _strip_marks(line)
                continue
            if current is not None:
                yield current
            rest = m.group("rest")
            sender, sep, text = rest.partition(": ")
            if not sep:
                current = _Message(when, None, _strip_marks(rest), "system")
                continue
            sender = _strip_marks(sender)
            flagged = text[:1] in _MARKS
            body = _EDITED.sub("", _strip_marks(text))
            if any(p.match(body) for p in _MEDIA):
                current = _Message(when, sender, "", "media", _media_kind(body))
            elif _DELETED.match(body) or body == "null":
                current = _Message(when, sender, "", "deleted")
            elif flagged:
                current = _Message(when, None, body, "system")
            else:
                current = _Message(when, sender, body, "text")
        if current is not None:
            yield current


def _tz(options: dict[str, Any], warnings: list[str] | None = None) -> ZoneInfo | timezone:
    name = (options.get("timezone") or "").strip()
    if not name:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        if warnings is not None:
            warnings.append(f"Unknown time zone {name!r}; times are read as UTC.")
        return timezone.utc


def _to_utc(local: datetime, tz) -> datetime:
    return local.replace(tzinfo=tz).astimezone(timezone.utc)


@dataclass
class _Turn:
    sender: str
    first: datetime
    last: datetime
    lines: list[str]
    messages: int
    media: list[str]


def _turns(messages: Iterator[_Message]) -> Iterator[_Turn]:
    gap = timedelta(minutes=settings.ECHO_IMPORT_TURN_GAP_MIN)
    cap = settings.ECHO_IMPORT_TURN_MAX_CHARS
    turn: _Turn | None = None
    for msg in messages:
        if msg.kind not in ("text", "media") or msg.sender is None:
            continue
        line = msg.text if msg.kind == "text" else f"[{msg.media}]"
        size = sum(len(x) + 1 for x in turn.lines) if turn else 0
        if (
            turn is not None
            and msg.sender == turn.sender
            and msg.when - turn.last <= gap
            and size + len(line) <= cap
        ):
            turn.lines.append(line)
            turn.last = msg.when
            turn.messages += 1
            if msg.kind == "media":
                turn.media.append(msg.media or "media")
            continue
        if turn is not None:
            yield turn
        turn = _Turn(msg.sender, msg.when, msg.when, [line], 1, [msg.media or "media"] if msg.kind == "media" else [])
    if turn is not None:
        yield turn


def _member(source: ImportSource) -> str | None:
    if not source.is_zip:
        return None
    member = _chat_member(source)
    if member is None:
        raise ExportUnreadable("No WhatsApp chat (.txt) was found in this zip.")
    return member


def _order(source: ImportSource, member: str | None, options: dict[str, Any]) -> tuple[str, bool]:
    forced = (options.get("date_order") or "auto").lower()
    if forced in ("dmy", "mdy", "ymd"):
        return forced, True
    return infer_date_order(source, member)


def preview(source: ImportSource, options: dict[str, Any]) -> ImportPreview:
    member = _member(source)
    order, decided = _order(source, member, options)
    warnings: list[str] = []
    if not decided:
        warnings.append(
            "No date in this chat shows whether it is day-first or month-first; "
            "it is read as day-first (31/01). Choose month-first if that is wrong."
        )
    stats = _Stats()

    def counted() -> Iterator[_Message]:
        # One pass: count everything while the turn grouper consumes it.
        for msg in _messages(source, member, order):
            if msg.kind == "system":
                stats.system += 1
            elif msg.kind == "deleted":
                stats.deleted += 1
            else:
                stats.messages += 1
                if msg.kind == "media":
                    stats.media += 1
                p = stats.participants.setdefault(msg.sender or "", {"name": msg.sender, "messages": 0})
                p["messages"] += 1
                stats.first_at = stats.first_at or msg.when
                stats.last_at = msg.when
            yield msg

    turns = sum(1 for _ in _turns(counted()))
    if stats.messages == 0:
        raise ExportUnreadable("No messages were found in this chat export.")
    tz = _tz(options, warnings)
    return ImportPreview(
        importer=NAME,
        label=LABEL,
        summary={
            "chat": chat_name(source),
            "messages": stats.messages,
            "media": stats.media,
            "system_lines": stats.system,
            "deleted": stats.deleted,
            "turns": turns,
            "first_at": _to_utc(stats.first_at, tz).isoformat() if stats.first_at else None,
            "last_at": _to_utc(stats.last_at, tz).isoformat() if stats.last_at else None,
            "date_order": order,
            "date_order_inferred": decided,
        },
        participants=sorted(stats.participants.values(), key=lambda p: -p["messages"]),
        options={"self_name": None, "redact_other_party": False, "timezone": None, "date_order": order},
        warnings=warnings,
    )


def parse_source(source: ImportSource, options: dict[str, Any], stats: dict[str, int]) -> Iterator[ImportedShare]:
    member = _member(source)
    order, _ = _order(source, member, options)
    tz = _tz(options)
    me = options.get("self_name") or None
    redact = bool(options.get("redact_other_party"))
    chat = chat_name(source)
    for turn in _turns(_messages(source, member, order)):
        mine = me is not None and turn.sender == me
        if redact and not mine:
            stats["redacted_turns"] = stats.get("redacted_turns", 0) + 1
            stats["redacted_messages"] = stats.get("redacted_messages", 0) + turn.messages
            continue
        words = [x for x in turn.lines if not (x.startswith("[") and x.endswith("]"))]
        if not any(w.strip() for w in words):
            stats["media_only_turns"] = stats.get("media_only_turns", 0) + 1
            continue
        first = _to_utc(turn.first, tz)
        yield ImportedShare(
            # The same turn imported again gets the same id.
            external_id=f"whatsapp:{stable_id(chat, turn.sender, first.isoformat())}",
            occurred_at=first,
            text="\n".join(turn.lines),
            author=turn.sender,
            author_is_tenant=mine,
            metadata={
                "content_type": CONTENT_TYPE,
                "chat": chat,
                "sender": turn.sender,
                "first_at": first.isoformat(),
                "last_at": _to_utc(turn.last, tz).isoformat(),
                "messages": turn.messages,
                "media": turn.media,
            },
        )


# ---------------------------------------------------------------------------
# The ArchiveImporter (registered in app/connectors/whatsapp/__init__.py)
# ---------------------------------------------------------------------------


class WhatsAppImporter:
    name = NAME
    display_name = LABEL
    # Other people's messages: the most sensitive thing Echo can hold.
    privacy_weight = "very_high"
    consent_disclosure = (
        "Reads a chat you exported from WhatsApp. Your messages become your own "
        "words; everyone else's are kept as context only (searchable, never "
        "quoted as yours, never a sample of your voice), or not at all if you "
        "keep only your side. The exported file itself is not kept."
    )
    content_type = CONTENT_TYPE

    def accepts(self, filename: str) -> bool:
        """By name only: WhatsApp's own export names. A renamed export is
        found by ``sniff``."""
        base = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
        return base == "_chat.txt" or (base.startswith("whatsapp chat") and base.endswith((".txt", ".zip")))

    def sniff(self, source: ImportSource) -> bool:
        return sniff(source)

    def preview(self, source: ImportSource, options: dict[str, Any]) -> ImportPreview:
        return preview(source, options)

    def parse(
        self,
        stream,
        *,
        tenant_id: str,
        options: dict[str, Any] | None = None,
        filename: str = "WhatsApp chat.txt",
        stats: dict[str, int] | None = None,
    ) -> Iterator[ImportedShare]:
        source = stream if isinstance(stream, ImportSource) else ImportSource(
            stream, filename, max_uncompressed=settings.ECHO_IMPORT_MAX_UNCOMPRESSED_BYTES
        )
        yield from parse_source(source, dict(options or {}), stats if stats is not None else {})


IMPORTER = WhatsAppImporter()
