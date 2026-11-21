"""How big a company is, as the company itself says it (size input, not size logic).

This module is the ONE place the band cut-offs live. They are PROVISIONAL and wait
for the owner's decision: nothing else may import or depend on the numbers. The
only things built on them are the answer options a person picks from and the
suggestion `derive_size_profile` makes, and a person confirms the suggestion
before it is stored. No threshold, approval or money rule reads the profile.

Derivation rule (pure, documented, tested):

  * volume (monthly outflow band) decides the profile: under the lower cut-off
    -> micro, between the cut-offs -> small, above the upper one -> medium;
  * headcount decides it only when volume was not answered: under 10 -> micro,
    10-49 -> small, 50 or more -> medium (the usual SME headcount classes);
  * when both are answered and disagree, VOLUME WINS and the result says so
    (`decided_by == "volume"`, `disagreement is True`), so the screen can name
    the answer that decided;
  * `has_inhouse_finance` is context only; it never changes the profile;
  * nothing answered -> no suggestion.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SizeProfile(StrEnum):
    MICRO = "micro"
    SMALL = "small"
    MEDIUM = "medium"


class SizeProfileSource(StrEnum):
    SELF_REPORTED = "self_reported"  # the person chose a profile themselves
    SUGGESTED_ACCEPTED = "suggested_accepted"  # the person accepted the derived suggestion


class OutflowBand(StrEnum):
    UNDER_500K = "under_500k"
    FROM_500K_TO_5M = "500k_to_5m"
    OVER_5M = "over_5m"


class HeadcountBand(StrEnum):
    UNDER_10 = "under_10"
    FROM_10_TO_49 = "10_to_49"
    FROM_50 = "50_plus"


# PROVISIONAL: awaiting the owner's decision. Monthly outflow, in lira. The labels
# are what the question shows; the cut-offs are stated once, here.
OUTFLOW_BAND_LABELS: dict[OutflowBand, str] = {
    OutflowBand.UNDER_500K: "500 bin ₺'nin altı",
    OutflowBand.FROM_500K_TO_5M: "500 bin ₺ – 5 milyon ₺",
    OutflowBand.OVER_5M: "5 milyon ₺'nin üstü",
}
HEADCOUNT_BAND_LABELS: dict[HeadcountBand, str] = {
    HeadcountBand.UNDER_10: "10'dan az",
    HeadcountBand.FROM_10_TO_49: "10 – 49",
    HeadcountBand.FROM_50: "50 ve üstü",
}

PROFILE_BY_OUTFLOW: dict[OutflowBand, SizeProfile] = {
    OutflowBand.UNDER_500K: SizeProfile.MICRO,
    OutflowBand.FROM_500K_TO_5M: SizeProfile.SMALL,
    OutflowBand.OVER_5M: SizeProfile.MEDIUM,
}
PROFILE_BY_HEADCOUNT: dict[HeadcountBand, SizeProfile] = {
    HeadcountBand.UNDER_10: SizeProfile.MICRO,
    HeadcountBand.FROM_10_TO_49: SizeProfile.SMALL,
    HeadcountBand.FROM_50: SizeProfile.MEDIUM,
}

# What the menu does when a profile is confirmed. Mirrored by the frontend's
# PROFILE_NAV (lib/nav-focus.ts); both are tested.
FOCUS_DEFAULT: dict[SizeProfile, bool] = {
    SizeProfile.MICRO: True,
    SizeProfile.SMALL: True,
    SizeProfile.MEDIUM: False,
}


@dataclass(frozen=True)
class Derivation:
    profile: SizeProfile
    decided_by: str  # "volume" | "headcount"
    disagreement: bool  # both answered and they point at different profiles


def derive_size_profile(
    outflow: OutflowBand | None, headcount: HeadcountBand | None
) -> Derivation | None:
    """The profile the answers suggest, or None when neither was answered."""
    by_volume = PROFILE_BY_OUTFLOW[outflow] if outflow is not None else None
    by_headcount = PROFILE_BY_HEADCOUNT[headcount] if headcount is not None else None
    if by_volume is not None:
        return Derivation(
            profile=by_volume,
            decided_by="volume",
            disagreement=by_headcount is not None and by_headcount != by_volume,
        )
    if by_headcount is not None:
        return Derivation(profile=by_headcount, decided_by="headcount", disagreement=False)
    return None
