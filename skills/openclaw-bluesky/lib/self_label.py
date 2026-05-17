"""self_label.py — Bluesky bot self-labeling (REQUIRED before any post).

Bluesky's policy requires automated accounts to self-label via the
`app.bsky.actor.profile` record with `$type: com.atproto.label.defs#selfLabels`
and a value of `bot`. Skipping this is one of the few documented suspension
triggers for autonomous accounts (2026 research dive 05).

Self-labels persist on the profile — call this once on first connect and on
any profile update that might overwrite the labels field.

Usage:
    from atproto import Client
    from self_label import ensure_bot_self_label

    client = Client()
    client.login(handle, app_password)
    ensure_bot_self_label(client)   # idempotent — safe to call every session

Spec source:
- https://docs.bsky.app/docs/starter-templates/bots (canonical)
- https://github.com/bluesky-social/atproto/blob/main/lexicons/app/bsky/actor/profile.json

The label value `bot` is community-conventional and matches how Bluesky's
moderation service surfaces bot accounts in client UIs.
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)


def _to_plain_dict(obj) -> dict:
    """Recursively convert a Pydantic model (or nested mix) to plain dicts/lists."""
    if obj is None:
        return {}
    # atproto SDK uses Pydantic v2 — prefer model_dump (with aliases so $type keys survive)
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(by_alias=True, exclude_none=True)
        except Exception:
            pass
    if hasattr(obj, "dict"):  # Pydantic v1 fallback
        try:
            return obj.dict(by_alias=True, exclude_none=True)
        except Exception:
            pass
    if isinstance(obj, dict):
        return obj
    # Last resort — best-effort
    return dict(obj)


def get_current_profile(client) -> Optional[dict]:
    """Fetch the current profile record (returns None if not yet created)."""
    try:
        resp = client.com.atproto.repo.get_record({
            "repo": client.me.did,
            "collection": "app.bsky.actor.profile",
            "rkey": "self",
        })
        return {
            "value": _to_plain_dict(resp.value),
            "cid": resp.cid,
            "uri": resp.uri,
        }
    except Exception as e:
        # Profile may not yet exist on a fresh account — that's fine, we'll create it
        log.debug(f"no profile record yet: {e}")
        return None


def _attr_or_key(obj, key: str, default=None):
    """Get a value by dict-key or model-attribute, whichever shape obj has."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        # Try alias key first ($type), then plain
        if key in obj:
            return obj[key]
        if key.startswith("$") and key[1:] in obj:
            return obj[key[1:]]
        return obj.get(key, default)
    # Attribute access — handle aliased $type → py_type convention
    attr_name = "py_type" if key == "$type" else key
    return getattr(obj, attr_name, default)


def is_already_self_labeled_as_bot(profile_value) -> bool:
    """Check if the profile already has the bot self-label.

    Handles both plain-dict profile values and atproto Pydantic-model shapes,
    since the SDK sometimes round-trips through models that don't expose .get().
    """
    labels = _attr_or_key(profile_value, "labels")
    if labels is None:
        return False
    if _attr_or_key(labels, "$type") != "com.atproto.label.defs#selfLabels":
        return False
    values = _attr_or_key(labels, "values") or []
    return any(_attr_or_key(v, "val") == "bot" for v in values)


def ensure_bot_self_label(client, label_value: str = "bot") -> dict:
    """Idempotently ensure the authenticated account is self-labeled as `bot`.

    Args:
        client: An authenticated atproto.Client instance.
        label_value: The label value to set. Default 'bot'.

    Returns:
        dict with keys: action ('skipped'|'set'|'updated'), profile_uri, label_value.

    Raises:
        Exception if the put_record call fails for reasons other than not-found.
    """
    current = get_current_profile(client)
    existing_value = (current or {}).get("value", {})

    if is_already_self_labeled_as_bot(existing_value):
        log.info(f"profile already self-labeled as {label_value}; skipping")
        return {
            "action": "skipped",
            "profile_uri": (current or {}).get("uri"),
            "label_value": label_value,
        }

    # Build the new profile record. Preserve all existing fields, add/overwrite labels.
    new_record = dict(existing_value)
    new_record["labels"] = {
        "$type": "com.atproto.label.defs#selfLabels",
        "values": [{"val": label_value}],
    }
    # Profile records require $type at top level
    new_record["$type"] = "app.bsky.actor.profile"

    put_args = {
        "repo": client.me.did,
        "collection": "app.bsky.actor.profile",
        "rkey": "self",
        "record": new_record,
    }
    # If the record exists, include the swap cid so we don't clobber concurrent edits
    if current and current.get("cid"):
        put_args["swap_record"] = current["cid"]

    resp = client.com.atproto.repo.put_record(put_args)
    log.info(f"profile self-labeled as {label_value}: uri={resp.uri}")
    action = "updated" if existing_value else "set"
    return {
        "action": action,
        "profile_uri": resp.uri,
        "label_value": label_value,
    }


if __name__ == "__main__":
    """CLI smoke test. Reads creds from env."""
    import os
    import sys
    from atproto import Client

    handle = os.environ.get("ARGOS_V2_BSKY_HANDLE") or os.environ.get("BSKY_HANDLE")
    app_pw = os.environ.get("ARGOS_V2_BSKY_APP_PASSWORD") or os.environ.get("BSKY_APP_PASSWORD")
    if not handle or not app_pw:
        print("set ARGOS_V2_BSKY_HANDLE + ARGOS_V2_BSKY_APP_PASSWORD (or BSKY_HANDLE/BSKY_APP_PASSWORD)")
        sys.exit(2)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = Client()
    client.login(handle, app_pw)
    result = ensure_bot_self_label(client)
    print(result)
