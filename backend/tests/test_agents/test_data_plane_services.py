from app.services.data_plane.normalization_service import normalize_csv_transactions
from app.services.data_plane.quality_gate_service import score_sync_quality


def test_normalize_csv_transactions_maps_basic_fields() -> None:
    csv_bytes = (
        b"date,amount,description,category,reference\n"
        b"2026-08-01,1250.50,Office rent,operations,INV-1\n"
    )
    rows = normalize_csv_transactions(csv_bytes=csv_bytes, column_mapping={})

    assert len(rows) == 1
    assert rows[0].amount_cents == 125050
    assert rows[0].description == "Office rent"
    assert rows[0].source_record_id == "INV-1"


def test_score_sync_quality_sets_review_band() -> None:
    result = score_sync_quality(validator_health_score=72, canonical_row_count=10)
    assert result.should_block is False
    assert result.should_review is True
    assert 0.50 <= result.quality_score < 0.80


def test_transactions_to_csv_roundtrip() -> None:
    from app.services.connectors.csv_utils import transactions_to_csv

    raw = transactions_to_csv(
        [
            {
                "date": "2026-08-01",
                "amount": 100.0,
                "description": "SaaS",
                "category": "revenue",
                "reference": "INV-1",
            }
        ]
    )
    assert b"2026-08-01" in raw
    assert b"100.0" in raw


def test_crm_export_base64() -> None:
    import asyncio
    import base64

    csv_text = "date,amount,description\n2026-08-01,500,Deal closed\n"
    encoded = base64.b64encode(csv_text.encode()).decode()

    async def _run() -> None:
        from app.services.connectors.crm_export import pull_crm_export_csv

        data, name = await pull_crm_export_csv({"csv_base64": encoded})
        assert name == "crm_export.csv"
        assert b"Deal closed" in data

    asyncio.run(_run())


def test_crm_hubspot_closed_won_maps_to_revenue_rows() -> None:
    import asyncio

    csv_text = (
        "Deal Name,Amount,Close Date,Deal Stage,Deal ID\n"
        "Acme,15000,2026-08-01,Closed Won,D-1\n"
        "Lost Co,9000,2026-08-02,Closed Lost,D-2\n"
    )

    async def _run() -> None:
        import base64

        from app.services.connectors.crm_export import pull_crm_export_csv

        encoded = base64.b64encode(csv_text.encode()).decode()
        data, name = await pull_crm_export_csv({"csv_base64": encoded})
        assert name == "crm_export.csv"
        text = data.decode()
        assert "Acme" in text
        assert "revenue" in text
        assert "Lost Co" not in text

    asyncio.run(_run())


def test_hr_payroll_maps_to_expense_rows() -> None:
    import asyncio
    import base64

    csv_text = "employee,salary,date,employee_id\nAda Lovelace,12000,2026-08-01,E-1\n"

    async def _run() -> None:
        from app.services.connectors.hr_export import pull_hr_export_csv

        encoded = base64.b64encode(csv_text.encode()).decode()
        data, name = await pull_hr_export_csv({"csv_base64": encoded})
        assert name == "hr_export.csv"
        text = data.decode()
        assert "Ada Lovelace" in text
        # The pipeline's vocabulary term is "salary"; "payroll" is not a
        # category it groups by, so rows carrying it vanished from every
        # report on cost.
        assert "salary" in text
        assert "payroll" not in text

    asyncio.run(_run())


def test_github_overlay_from_activity() -> None:
    from types import SimpleNamespace

    from app.services.connectors.github_activity import overlay_from_github_data
    from app.services.connectors.registry import list_connectors

    data = SimpleNamespace(
        owner="acme",
        repo="core",
        commits=[object()] * 45,
        pull_requests=[object()] * 3,
        issues=[],
        open_issues=2,
    )
    overlay = overlay_from_github_data(data)
    assert overlay["cto_summary"]["velocity_trend"] == "up"
    assert overlay["github_activity"]["commit_count"] == 45
    live_ids = {c["id"] for c in list_connectors(live_only=True)}
    assert "github_activity" in live_ids
    assert "hr_export" in live_ids

