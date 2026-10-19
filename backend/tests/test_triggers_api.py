"""P4-4 /tetikler API: contract-validated CRUD, org scoping, audit, dry-run.

The engine suite pins what a stored rule *does*; this suite pins how one gets
stored — that the API only persists contract-valid rows, that a caller can
never touch another org's rules, and that the dry-run endpoint evaluates a
condition without firing anything.
"""
from __future__ import annotations

from tests.api_helpers import bellek_istemcisi, kullanici

RAKIM_KOSUL = {"metric": "finance.runway_months", "op": "lt", "value": 3}


async def test_meta_lists_catalogs_for_the_ui():
    async with bellek_istemcisi() as client:
        headers, _, _ = await kullanici(client, "meta@ornek.com")
        res = await client.get("/api/v1/tetikler/meta", headers=headers)
        assert res.status_code == 200
        data = res.json()["data"]
        assert set(data["action_kinds"]) == {
            "alert.dispatch", "analysis.start", "cascade.simulate",
            "report.generate", "webhook.call",
        }
        assert set(data["event_kinds"]) == {
            "job.completed", "tx.arrived", "anomaly.detected", "schedule",
        }
        assert "abs_gt" in data["operators"]
        assert any(m["id"] == "finance.runway_months" for m in data["metrics"])
        assert "cash_crisis" in data["cascade_triggers"]


async def test_create_list_get_roundtrip():
    async with bellek_istemcisi() as client:
        headers, org_id, _ = await kullanici(client, "olustur@ornek.com")
        res = await client.post(
            "/api/v1/tetikler",
            headers=headers,
            json={
                "name": "Runway alarmla",
                "events": ["job.completed"],
                "condition": RAKIM_KOSUL,
                "action_kind": "alert.dispatch",
                "action_params": {"severity": "critical"},
                "cooldown_minutes": 30,
            },
        )
        assert res.status_code == 201
        created = res.json()["data"]
        assert created["org_id"] == org_id
        assert created["action_kind"] == "alert.dispatch"
        assert created["cooldown_minutes"] == 30
        assert created["enabled"] is True
        assert created["condition"] == RAKIM_KOSUL

        listed = (await client.get("/api/v1/tetikler", headers=headers)).json()["data"]
        assert [t["id"] for t in listed["triggers"]] == [created["id"]]

        fetched = await client.get(
            f"/api/v1/tetikler/{created['id']}", headers=headers
        )
        assert fetched.status_code == 200
        assert fetched.json()["data"]["name"] == "Runway alarmla"


async def test_create_rejects_unknown_kinds_and_bad_condition():
    async with bellek_istemcisi() as client:
        headers, _, _ = await kullanici(client, "hata@ornek.com")
        base = {
            "name": "kural", "events": ["job.completed"],
            "condition": RAKIM_KOSUL, "action_kind": "alert.dispatch",
        }

        bad_action = await client.post(
            "/api/v1/tetikler", headers=headers,
            json={**base, "action_kind": "email.explode"},
        )
        assert bad_action.status_code == 400
        assert "aksiyon" in bad_action.json()["error"]

        bad_event = await client.post(
            "/api/v1/tetikler", headers=headers,
            json={**base, "events": ["full.moon"]},
        )
        assert bad_event.status_code == 400
        assert "olay" in bad_event.json()["error"]

        bad_condition = await client.post(
            "/api/v1/tetikler", headers=headers,
            json={**base, "condition": {"metric": "finance.runway_months"}},
        )
        assert bad_condition.status_code == 400
        assert "Geçersiz koşul" in bad_condition.json()["error"]

        missing = await client.post("/api/v1/tetikler", headers=headers, json={})
        assert missing.status_code == 400
        assert "Zorunlu" in missing.json()["error"]


async def test_patch_merges_revalidates_and_leaves_row_on_error():
    async with bellek_istemcisi() as client:
        headers, _, _ = await kullanici(client, "guncel@ornek.com")
        created = (await client.post(
            "/api/v1/tetikler", headers=headers,
            json={
                "name": "kural", "events": ["schedule"],
                "condition": RAKIM_KOSUL, "action_kind": "alert.dispatch",
            },
        )).json()["data"]

        ok = await client.patch(
            f"/api/v1/tetikler/{created['id']}", headers=headers,
            json={"enabled": False, "cooldown_minutes": 5},
        )
        assert ok.status_code == 200
        updated = ok.json()["data"]
        assert updated["enabled"] is False
        assert updated["cooldown_minutes"] == 5
        # Untouched fields survive the merge.
        assert updated["name"] == "kural"
        assert updated["condition"] == RAKIM_KOSUL

        bad = await client.patch(
            f"/api/v1/tetikler/{created['id']}", headers=headers,
            json={"condition": {"op": "lt"}},
        )
        assert bad.status_code == 400
        still = (await client.get(
            f"/api/v1/tetikler/{created['id']}", headers=headers
        )).json()["data"]
        assert still["condition"] == RAKIM_KOSUL


async def test_org_isolation_hides_foreign_rules():
    async with bellek_istemcisi() as client:
        headers_a, _, _ = await kullanici(client, "a@ornek.com")
        headers_b, _, _ = await kullanici(client, "b@ornek.com")
        created = (await client.post(
            "/api/v1/tetikler", headers=headers_a,
            json={
                "name": "a-kural", "events": ["schedule"],
                "condition": RAKIM_KOSUL, "action_kind": "alert.dispatch",
            },
        )).json()["data"]

        listed_b = (await client.get("/api/v1/tetikler", headers=headers_b)).json()
        assert listed_b["data"]["triggers"] == []

        for method, url in (
            ("get", f"/api/v1/tetikler/{created['id']}"),
            ("patch", f"/api/v1/tetikler/{created['id']}"),
            ("delete", f"/api/v1/tetikler/{created['id']}"),
        ):
            res = await getattr(client, method)(
                url, headers=headers_b, **({"json": {"enabled": False}} if method == "patch" else {})
            )
            assert res.status_code == 404, method

        # A's rule is untouched by B's rejected attempts.
        still = (await client.get(
            f"/api/v1/tetikler/{created['id']}", headers=headers_a
        )).json()["data"]
        assert still["enabled"] is True


async def test_delete_removes_rule():
    async with bellek_istemcisi() as client:
        headers, _, _ = await kullanici(client, "sil@ornek.com")
        created = (await client.post(
            "/api/v1/tetikler", headers=headers,
            json={
                "name": "kural", "events": ["schedule"],
                "condition": RAKIM_KOSUL, "action_kind": "alert.dispatch",
            },
        )).json()["data"]

        res = await client.delete(f"/api/v1/tetikler/{created['id']}", headers=headers)
        assert res.status_code == 200
        assert res.json()["data"]["deleted"] is True
        assert (await client.get(
            f"/api/v1/tetikler/{created['id']}", headers=headers
        )).status_code == 404


async def test_runs_are_org_scoped_and_filterable():
    async with bellek_istemcisi() as client:
        headers_a, org_a, _ = await kullanici(client, "defter-a@ornek.com")
        headers_b, org_b, _ = await kullanici(client, "defter-b@ornek.com")

        from app.models.trigger import TriggerRunRow

        async with client._maker() as db:  # type: ignore[attr-defined]
            db.add(TriggerRunRow(
                org_id=org_a, trigger_id="trg-1", event_kind="job.completed",
                event_ref="job-1", status="fired",
            ))
            db.add(TriggerRunRow(
                org_id=org_a, trigger_id="trg-2", event_kind="schedule",
                event_ref="day-1", status="condition_false",
            ))
            db.add(TriggerRunRow(
                org_id=org_b, trigger_id="trg-9", event_kind="schedule",
                event_ref="day-1", status="fired",
            ))
            await db.commit()

        runs_a = (await client.get("/api/v1/tetikler/runs", headers=headers_a)).json()["data"]["runs"]
        assert {r["trigger_id"] for r in runs_a} == {"trg-1", "trg-2"}

        filtered = (await client.get(
            "/api/v1/tetikler/runs?trigger_id=trg-1", headers=headers_a
        )).json()["data"]["runs"]
        assert [r["trigger_id"] for r in filtered] == ["trg-1"]
        assert filtered[0]["status"] == "fired"

        runs_b = (await client.get("/api/v1/tetikler/runs", headers=headers_b)).json()["data"]["runs"]
        assert [r["trigger_id"] for r in runs_b] == ["trg-9"]


async def test_dry_run_evaluates_without_firing_or_writing():
    async with bellek_istemcisi() as client:
        headers, _, _ = await kullanici(client, "dry@ornek.com")

        low = await client.post(
            "/api/v1/tetikler/dry-run", headers=headers,
            json={"condition": RAKIM_KOSUL, "values": {"finance.runway_months": 2.5}},
        )
        assert low.status_code == 200
        assert low.json()["data"]["would_fire"] is True

        high = await client.post(
            "/api/v1/tetikler/dry-run", headers=headers,
            json={"condition": RAKIM_KOSUL, "values": {"finance.runway_months": 10.0}},
        )
        assert high.json()["data"]["would_fire"] is False

        unknown = await client.post(
            "/api/v1/tetikler/dry-run", headers=headers,
            json={"condition": {"metric": "olmayan.metrik", "op": "gt", "value": 1},
                  "values": {}},
        )
        assert unknown.json()["data"]["unknown_metrics"] == ["olmayan.metrik"]

        bad = await client.post(
            "/api/v1/tetikler/dry-run", headers=headers,
            json={"condition": {"metric": "x"}, "values": {}},
        )
        assert bad.status_code == 400

        # A dry run writes nothing: no rules, no audit rows.
        assert (await client.get("/api/v1/tetikler", headers=headers)).json()["data"]["triggers"] == []
        assert (await client.get("/api/v1/tetikler/runs", headers=headers)).json()["data"]["runs"] == []


async def test_stored_rule_engine_roundtrip_through_api_row():
    """A rule created via the API must evaluate in the engine unchanged."""
    async with bellek_istemcisi() as client:
        headers, _, _ = await kullanici(client, "motor@ornek.com")
        created = (await client.post(
            "/api/v1/tetikler", headers=headers,
            json={
                "name": "motor turu",
                "events": ["job.completed"],
                "condition": {
                    "any": [
                        RAKIM_KOSUL,
                        {"metric": "finance.critical_anomalies", "op": "gt", "value": 0},
                    ]
                },
                "action_kind": "alert.dispatch",
                "cooldown_minutes": 0,
            },
        )).json()["data"]

        from app.services.triggers import evaluate, row_to_definition

        async with client._maker() as db:  # type: ignore[attr-defined]
            from app.models.trigger import TriggerDefinitionRow

            row = await db.get(TriggerDefinitionRow, created["id"])
            assert row is not None
            definition = row_to_definition(row)

        assert definition.name == "motor turu"
        assert evaluate(definition.condition, {"finance.runway_months": 2.0}) is True
        assert evaluate(definition.condition, {"finance.critical_anomalies": 1}) is True
        assert evaluate(definition.condition, {"finance.runway_months": 9.0}) is False
