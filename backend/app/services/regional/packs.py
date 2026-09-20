"""Regional pack helpers — feature gates for locale-specific modules."""
from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Any

# Pack id → API path prefixes / nav hrefs gated behind the pack
TR_PACK_ID = "tr"

TR_PACK_PATH_PREFIXES: tuple[str, ...] = (
    "/smmm",
    "/smmm-onay",
    "/muhasebe",
    "/efatura",
    "/gib",
)

TR_PACK_NAV_HREFS: frozenset[str] = frozenset(
    {
        "/smmm",
        "/smmm-onay",
    }
)

TR_ERP_PROVIDERS: frozenset[str] = frozenset({"parasut", "logo_tiger", "mikro", "netsis"})


def normalize_packs(packs: Any) -> list[str]:
    if packs is None:
        return []
    if isinstance(packs, str):
        return [p.strip().lower() for p in packs.split(",") if p.strip()]
    if isinstance(packs, (list, tuple, set)):
        return [str(p).strip().lower() for p in packs if str(p).strip()]
    return []


def org_has_pack(org: Any, pack_id: str) -> bool:
    packs = normalize_packs(getattr(org, "regional_packs", None))
    return pack_id.lower() in packs


def org_has_tr_pack(org: Any) -> bool:
    return org_has_pack(org, TR_PACK_ID)


def path_requires_tr_pack(path: str) -> bool:
    p = path.rstrip("/") or "/"
    return any(p == prefix or p.startswith(prefix + "/") for prefix in TR_PACK_PATH_PREFIXES)


def filter_nav_items_for_packs(
    items: Iterable[dict[str, Any]],
    packs: Collection[str],
) -> list[dict[str, Any]]:
    pack_set = {str(p).lower() for p in packs}
    has_tr = TR_PACK_ID in pack_set
    out: list[dict[str, Any]] = []
    for item in items:
        href = str(item.get("href") or "")
        if href in TR_PACK_NAV_HREFS and not has_tr:
            continue
        out.append(item)
    return out
