"""
Plan v11 §8: architecture fitness functions that make the target checkable.

F1 (import direction) lives in test_architecture_boundaries.py. This file adds:

- F2  no module under app/ is longer than 600 lines;
- F3  only the delivery service talks SMTP (a future outbox sender will be the only one);
- F5  every module under app/ is imported by something in app/.

Each starts as a ratchet: today's violations are listed, a NEW violation fails,
and a listed entry that no longer violates fails too, so the list can only shrink.
When you fix one, delete its line.
"""

from __future__ import annotations

import ast
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_APP = _BACKEND / "app"

MAX_LINES = 600

# F2: modules over the ceiling on 2026-11-14. Plan v11 C1, C6, C8, C9, C10 split them.
_OVERSIZED: frozenset[str] = frozenset(
    {
        "app/agents/ceo/synthesis_agent.py",
        "app/agents/orchestration/auto_chain.py",
        "app/api/ceo.py",
        "app/api/chat.py",
        "app/api/compliance_extended.py",
        "app/api/muhasebe.py",
        "app/api/org.py",
        "app/scheduler.py",
        "app/services/benchmark.py",
        "app/services/benchmark_utils.py",
        "app/services/cascade_simulator.py",
        "app/services/csv_validator.py",
        "app/services/llm_structured.py",
        "app/services/reasoning_loop.py",
        "app/services/scheduled_sync.py",
        "app/worker.py",
    }
)

# F3: the modules allowed to import an SMTP client.
_SMTP_ALLOWED: frozenset[str] = frozenset({"app.services.outbox_transport"})

# F3 (outward effects): modules whose Slack, e-mail and webhook effects must be written
# to the outbox (ADR 0003), never sent inline. The imports and calls below are senders.
_OUTBOX_ONLY: frozenset[str] = frozenset(
    {"app.agents.orchestration.proactive_alerts", "app.services.triggers.actions"}
)
_SENDER_MODULES = (
    "httpx", "aiosmtplib", "smtplib", "requests", "app.services.alert_dispatcher",
    "app.services.integrations", "app.services.outbox_transport",
)
_SENDER_CALLS: frozenset[str] = frozenset(
    {"dispatch_slack", "dispatch_webhook", "send_plain_email", "_send_slack_message",
     "_send_email", "_send_slack", "send_slack", "send_teams", "send_whatsapp", "send_slack_bot",
     "send_custom", "send_email", "_send_whatsapp"}
)


def _direct_senders(name: str, path: Path) -> set[str]:
    found = {
        i for i in _imports(name, path)
        if any(i == m or i.startswith(m + ".") for m in _SENDER_MODULES)
    }
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8", errors="replace"))):
        if isinstance(node, ast.Attribute) and node.attr in _SENDER_CALLS:
            found.add(f".{node.attr}")
    return found


# F5: modules nothing in app/ imports, on 2026-11-14. Some are reached only from
# scripts, tests, a string in importlib or a CLI; each is examined before it is
# deleted (plan v11 A0.2 removed the three that had no caller at all).
_UNIMPORTED: frozenset[str] = frozenset(
    {
        "app.core.crypto",
        "app.core.distributed_lock",
        "app.core.tenancy",
        "app.services.audit_trail",
        "app.services.benchmark_utils",
        "app.services.consolidation_engine",
        "app.services.demo_seeder",
        "app.services.edefter_package",
        "app.services.eval_harness",
        "app.services.field_encryption",
        "app.services.gib_edefter_ws",
        "app.services.inflation_accounting",
        "app.services.prescriptive_recommender",
        "app.services.regional.tax_calculator",
        "app.services.retry_harness",
        "app.services.smmm_adopt",
    }
)

# Entry points and modules loaded by the framework rather than imported.
_ENTRY_POINTS: frozenset[str] = frozenset(
    {"app", "app.main", "app.worker", "app.scheduler", "app.config", "app.database", "app.mcp.__main__"}
)
_LOADED_BY_FRAMEWORK = ("app.api.", "app.models.")


def _modules() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in _APP.rglob("*.py"):
        parts = path.relative_to(_BACKEND).with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        found[name] = path
    return found


def _imports(name: str, path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), str(path))
    package = name if path.name == "__init__.py" else name.rsplit(".", 1)[0]
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                head = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join(head + ([base] if base else []))
            out.add(base)
            out.update(f"{base}.{alias.name}" for alias in node.names)
    return out


def _line_count(path: Path) -> int:
    with path.open(encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle)


def _oversized() -> set[str]:
    return {
        path.relative_to(_BACKEND).as_posix()
        for path in _modules().values()
        if _line_count(path) > MAX_LINES
    }


def _smtp_importers() -> set[str]:
    return {
        name
        for name, path in _modules().items()
        if any(i == "aiosmtplib" or i.startswith("aiosmtplib.") for i in _imports(name, path))
    }


def _unimported() -> set[str]:
    modules = _modules()
    imported: set[str] = set()
    for name, path in modules.items():
        imported |= _imports(name, path)

    def reached(module: str) -> bool:
        return any(i == module or i.startswith(module + ".") for i in imported)

    return {
        name
        for name in modules
        if name not in _ENTRY_POINTS
        and not name.startswith(_LOADED_BY_FRAMEWORK)
        and modules[name].name != "__init__.py"
        and not reached(name)
    }


def test_f2_no_new_module_over_the_line_ceiling() -> None:
    new = sorted(_oversized() - _OVERSIZED)
    assert not new, (
        f"Over {MAX_LINES} lines: {new}. Split by responsibility (plan v11 F2); "
        "do not add to the list."
    )


def test_f2_list_shrinks_when_a_module_is_split() -> None:
    stale = sorted(_OVERSIZED - _oversized())
    assert not stale, f"No longer over {MAX_LINES} lines; delete from _OVERSIZED: {stale}"


def test_f3_only_the_delivery_service_talks_smtp() -> None:
    importers = _smtp_importers()
    assert importers <= _SMTP_ALLOWED, (
        f"SMTP used outside the delivery service: {sorted(importers - _SMTP_ALLOWED)}. "
        "Write the message to the delivery path instead (plan v11 C9, F3)."
    )


def test_f3_alerts_and_trigger_webhooks_go_through_the_outbox() -> None:
    modules = _modules()
    assert set(modules) >= _OUTBOX_ONLY
    direct = {m: sorted(_direct_senders(m, modules[m])) for m in _OUTBOX_ONLY}
    assert not any(direct.values()), (
        f"Outward effect sent inline: {direct}. Write an outbox row instead "
        "(app.services.outbox.enqueue / enqueue_slack / enqueue_webhook; ADR 0003, F3)."
    )


def test_f3_notification_slack_goes_through_the_outbox() -> None:
    """The notification service's Slack path writes an outbox row; it has no sender of its own.

    So do its e-mail and WhatsApp paths: it holds no client of any kind."""
    path = _modules()["app.services.notification_service"]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef)}
    called = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "_send_slack" not in defined | called, "Slack must not be sent inline (ADR 0003, F3)"
    assert {"enqueue_slack", "enqueue_whatsapp", "enqueue"} <= called, "every channel must write an outbox row"
    inline_http = {
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef)
        and any(
            isinstance(n, ast.Import | ast.ImportFrom)
            and "httpx" in ast.dump(n)
            for n in ast.walk(fn)
        )
    }
    assert not inline_http, f"inline HTTP sender: {sorted(inline_http)}"


def test_f3_the_check_sees_a_direct_send(tmp_path: Path) -> None:
    sender = tmp_path / "sender.py"
    sender.write_text(
        "from app.services.alert_dispatcher import AlertDispatcher\n"
        "async def f(url):\n    await AlertDispatcher.dispatch_slack(url, 't', 'm')\n",
        encoding="utf-8",
    )
    assert _direct_senders("app.sender", sender) == {
        "app.services.alert_dispatcher",
        "app.services.alert_dispatcher.AlertDispatcher",
        ".dispatch_slack",
    }


def test_f5_no_new_module_without_a_caller() -> None:
    new = sorted(_unimported() - _UNIMPORTED)
    assert not new, (
        f"Nothing in app/ imports {new}. Wire it in where it is used, or do not add it "
        "(plan v11 F5)."
    )


def test_f5_list_shrinks_when_a_module_gets_a_caller_or_goes() -> None:
    stale = sorted(_UNIMPORTED - _unimported())
    assert not stale, f"Now imported or deleted; remove from _UNIMPORTED: {stale}"


# ── F3, whole application: nothing outside the outbox sender sends ───────────

# The only modules that may hold a mail, WhatsApp, Slack or webhook client. `outbox` is the
# one that calls the other two (transport: SMTP, WhatsApp, Slack bot; dispatcher: Slack and
# webhook POSTs).
_SENDERS: frozenset[str] = frozenset(
    {"app.services.outbox", "app.services.outbox_transport", "app.services.alert_dispatcher"}
)
_SENDER_IMPORTS = (
    "aiosmtplib", "smtplib", "twilio", "sendgrid", "slack_sdk", "pywebpush", "boto3", "mailgun",
    "postmarker", "resend", "app.services.alert_dispatcher", "app.services.outbox_transport",
)
_SENDER_ATTRS: frozenset[str] = frozenset(
    {"dispatch_slack", "dispatch_webhook", "send_plain_email", "send_whatsapp", "send_slack_bot",
     "send_slack", "send_teams", "send_custom", "send_email", "_send_email", "_send_slack",
     "_send_whatsapp", "sendmail", "send_message"}
)
_PROVIDER_HOSTS = (
    "graph.facebook.com", "api.twilio.com", "slack.com/api", "hooks.slack.com", "outlook.office.com/webhook",
)
_HTTP_VERBS = frozenset({"post", "put", "patch", "delete", "request", "send"})

# Modules that make an HTTP write to a service which is not a recipient of ours: a login or token
# exchange with a system the company connects, or our own API. Each says why it is not an outward
# effect. A new entry needs the same sentence; a module that notifies a person is not one.
_HTTP_WRITERS: dict[str, str] = {
    "app.core.outbound": "the one guarded client for a URL a user typed (https, public addresses only, pinned)",
    "app.mcp.server": "client of our own API at a configured base URL",
    "app.services.erp.parasut_connector": "OAuth token exchange with the ERP the company connected (pull)",
    "app.services.gib_efatura": "login and queries against GIB (pull)",
    "app.services.gib_edefter_ws": "files an e-Defter package with GIB; imported by nothing: needs a release gate before it is wired",
    "app.services.integrations": "OAuth token exchange of the open-banking connector (pull)",
    "app.services.open_banking.base": "OAuth token exchange with the bank (pull)",
    "app.services.sso": "token exchange with the sign-in provider",
}


def _imports_httpx(tree: ast.AST) -> bool:
    return any(
        (isinstance(n, ast.Import) and any(a.name == "httpx" or a.name.startswith("httpx.") for a in n.names))
        or (isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "httpx")
        for n in ast.walk(tree)
    )


def _sender_findings(name: str, path: Path) -> set[str]:
    """What in this module sends, or could: a provider import, call, URL, or an HTTP write."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    found = {
        f"import {i}" for i in _imports(name, path)
        if any(i == m or i.startswith(m + ".") for m in _SENDER_IMPORTS)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _SENDER_ATTRS:
            found.add(f"call .{node.attr}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.update(f"url {h}" for h in _PROVIDER_HOSTS if h in node.value)
    if _imports_httpx(tree) and name not in _HTTP_WRITERS:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _HTTP_VERBS:
                receiver = node.func.value
                label = receiver.id if isinstance(receiver, ast.Name) else getattr(receiver, "attr", "?")
                if label not in {"router", "app", "api"}:  # a route decorator, not a client
                    found.add(f"http .{node.func.attr}")
    return found


def test_f3_no_module_outside_the_outbox_sender_talks_to_a_provider() -> None:
    offenders = {
        name: sorted(found)
        for name, path in _modules().items()
        if name not in _SENDERS and name != "app.config" and (found := _sender_findings(name, path))
    }
    assert not offenders, (
        f"Outward effect outside the outbox sender: {offenders}. Write an outbox row instead "
        "(app.services.outbox / outbox_immediate), or, for a pull from a system the company connected, "
        "list the module in _HTTP_WRITERS with the reason (F3, ADR 0003)."
    )


# Modules that import httpx. Each talks to a FIXED, code-owned host (or an operator-set base URL),
# never to a URL a user typed; a user-supplied URL goes through app.core.outbound (SSRF guard).
_FIXED_HOST_HTTP_CLIENTS = frozenset({
    "app.core.outbound", "app.mcp.server", "app.services.alert_dispatcher", "app.services.benchmark",
    "app.services.erp.parasut_connector", "app.services.gib_edefter_ws", "app.services.gib_efatura",
    "app.services.github_connector", "app.services.integrations", "app.services.open_banking.base",
    "app.services.outbox_transport", "app.services.sso", "app.services.tcmb_macro",
})


def _variable_host_urls(tree: ast.AST) -> list[int]:
    """Line numbers of URL strings whose HOST is not a literal constant.

    `f"https://{x}/..."`, `f"https://{x}.example.com/..."` is a variable label, `"https://" + x`.
    A literal host followed by a variable path (`f"https://api.example.com/{id}"`) is fine."""
    found: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) and node.values:
            first = node.values[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value.startswith(
                ("https://", "http://")
            ):
                literal = first.value.split("://", 1)[1]
                if "/" in literal:
                    continue  # the host is complete in the literal prefix
                found.append(node.lineno)
        if (
            isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)
            and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str)
            and node.left.value.startswith(("https://", "http://")) and "/" not in node.left.value.split("://", 1)[1]
        ):
            found.append(node.lineno)
    return found


# A variable host label is allowed only on a literal registrable suffix and with a strict check.
_VALIDATED_LABEL_HOSTS: dict[str, str] = {
    "app.services.integrations": ".myshopify.com",  # ShopifyConnector._SHOP_LABEL
}


def test_f3_fixed_host_modules_really_have_literal_hosts() -> None:
    """"Fixed host" is checked, not declared: no module builds a URL with a variable host unless it is
    listed with the literal suffix it keeps and the strict label check that goes with it."""
    offenders: dict[str, list[int]] = {}
    for name, path in _modules().items():
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = _variable_host_urls(ast.parse(text))
        if lines and name not in _VALIDATED_LABEL_HOSTS:
            offenders[name] = lines
    assert not offenders, (
        f"URL with a variable host in {offenders}. A host from input must go through app.core.outbound "
        "and a strict pattern; list it in _VALIDATED_LABEL_HOSTS only with both."
    )
    for name, suffix in _VALIDATED_LABEL_HOSTS.items():
        text = _modules()[name].read_text(encoding="utf-8")
        assert suffix in text and "_SHOP_LABEL" in text and "outbound.request" in text, name
        assert f'"https://{{label}}{suffix}' in text, "the literal suffix must follow the variable label"


def test_f3_the_host_check_sees_a_variable_host() -> None:
    bad = ast.parse('u = f"https://{shop}/admin"; v = "https://" + shop; w = f"https://{s}.x.com/a"')
    good = ast.parse('u = f"https://api.x.com/{i}"')
    assert len(_variable_host_urls(bad)) == 3 and _variable_host_urls(good) == []


def test_f3_user_supplied_urls_never_reach_a_raw_http_client() -> None:
    """A new module that imports httpx must be classified: fixed host, or use app.core.outbound."""
    modules = _modules()
    clients = {
        n for n, path in modules.items()
        if _imports_httpx(ast.parse(path.read_text(encoding="utf-8", errors="replace")))
        or "import httpx" in path.read_text(encoding="utf-8", errors="replace")
    }
    unknown = sorted(clients - _FIXED_HOST_HTTP_CLIENTS)
    assert not unknown, (
        f"{unknown} import httpx. A URL a user typed (webhook, CSV import, base URL) must go through "
        "app.core.outbound.request; if the host is fixed in code, add the module to "
        "_FIXED_HOST_HTTP_CLIENTS with that reason."
    )
    # The two CSV connectors take a user URL: they must use the guard, not a client of their own.
    for name in ("app.services.connectors.crm_export", "app.services.connectors.hr_export"):
        assert "outbound.fetch_import" in modules[name].read_text(encoding="utf-8")


def test_f3_the_http_write_allowlist_has_no_dead_entries() -> None:
    modules = _modules()
    stale = sorted(
        n for n in _HTTP_WRITERS
        if n not in modules or not _imports_httpx(ast.parse(modules[n].read_text(encoding="utf-8")))
    )
    assert not stale, f"Not an HTTP client any more; delete from _HTTP_WRITERS: {stale}"


def test_f3_the_senders_are_who_we_expect() -> None:
    assert set(_modules()) >= _SENDERS
    assert _smtp_importers() == {"app.services.outbox_transport"}


def test_f3_the_immediate_class_is_written_only_by_its_allowlist_module() -> None:
    """`delivery_class="immediate"` is what lets a message skip release; only outbox_immediate sets it."""
    allowed = {"app.services.outbox", "app.services.outbox_immediate", "app.models.outbox_message"}
    found: set[str] = set()
    for name, path in _modules().items():
        if name in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "delivery_class":
                found.add(name)
            if isinstance(node, ast.Name) and node.id == "IMMEDIATE":
                found.add(name)
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "OutboxMessage":
                found.add(name)
    assert not found, (
        f"{sorted(found)} write outbox rows or the immediate class directly. Use outbox.enqueue "
        "(released) or an outbox_immediate.enqueue_* function (allowlisted kinds)."
    )


def test_f3_the_check_sees_each_kind_of_sender(tmp_path: Path) -> None:
    cases = {
        "smtp": ("import aiosmtplib\n", {"import aiosmtplib"}),
        "call": ("def f(n):\n    n.send_whatsapp('1', 'x')\n", {"call .send_whatsapp"}),
        "url": ("U = 'https://graph.facebook.com/v19.0/1/messages'\n", {"url graph.facebook.com"}),
        "http": ("import httpx\nasync def f(c):\n    await c.post('https://x.example')\n", {"http .post"}),
        "route": (
            "import httpx\nfrom fastapi import APIRouter\nrouter = APIRouter()\n@router.post('/x')\ndef f(): ...\n",
            set(),
        ),
    }
    for label, (source, expected) in cases.items():
        path = tmp_path / f"{label}.py"
        path.write_text(source, encoding="utf-8")
        assert _sender_findings(f"app.{label}", path) == expected, label
