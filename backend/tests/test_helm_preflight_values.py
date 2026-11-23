"""The Helm chart can pass the production preflight for the settings that have no safe default: the public app address
and the two notice links (`required`, so `helm template` refuses a missing one instead of deploying a backend that will
not start). Text checks, so it runs without helm installed."""
from __future__ import annotations

from pathlib import Path

CHART = Path(__file__).resolve().parents[2] / "helm" / "agentic-cfo"


def test_the_configmap_sets_the_public_address_and_requires_the_notice_links() -> None:
    cm = (CHART / "templates" / "configmap.yaml").read_text(encoding="utf-8")
    assert 'FRONTEND_URL: "https://{{ (index .Values.ingress.hosts 0).host }}"' in cm
    assert 'BRAND_APP_URL: "https://{{ (index .Values.ingress.hosts 0).host }}"' in cm
    assert 'PRIVACY_NOTICE_URL: {{ required "' in cm and "config.privacyNoticeUrl" in cm
    assert 'TERMS_URL: {{ required "' in cm and "config.termsUrl" in cm


def test_the_values_file_declares_the_links_without_a_default() -> None:
    import yaml

    config = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))["config"]
    assert config["privacyNoticeUrl"] == "" and config["termsUrl"] == ""  # empty: `required` fails until the operator sets them
