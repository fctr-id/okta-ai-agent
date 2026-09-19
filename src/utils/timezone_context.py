"""Validated client timezone context; never infer a user's zone from the server."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def normalize_user_timezone(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("user_timezone must be a valid IANA timezone") from exc
    return value


def timezone_instructions(user_timezone: str | None) -> str:
    return f"""TIMEZONE CONTEXT
Client timezone default: {user_timezone or '(not provided)'}.
Use an explicit timezone in the user's request or established conversation in
preference to this default. Use the client default for 'local time'; never use
the server's local timezone. Ask for clarification if no target zone is known.
Convert timezones only when requested or established by the conversation;
the presence of a client default alone is not a request to convert timestamps.
Use IANA timezone names and datetime.astimezone(ZoneInfo(target_zone)); do not
write manual offsets or daylight-saving rules. Parse ISO timestamps using
datetime.fromisoformat(value.replace('Z', '+00:00')). Z means UTC. Native Okta
timestamps normalized by our sync are UTC even if the SQL serialization omits
the offset: attach timezone.utc to those naive values before conversion.
Do not assume arbitrary naive profile/custom timestamps are UTC or reinterpret
already converted saved values. Preserve nulls and label the output timezone.
Keep timestamp values in saved/result rows in ISO 8601 form using isoformat(),
preserving the numeric UTC offset and precision. Do not replace them with
strftime display strings or timezone abbreviations. If a different display
format is explicitly requested, retain the ISO timestamp alongside that display.
"""
