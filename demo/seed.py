#!/usr/bin/env python3
"""
AI CFO Suite — Demo Seed Script
================================
Uploads sample Logo Tiger financial data and triggers analysis.
Run after `docker-compose up` or against local backend.

Usage:
    python demo/seed.py                          # uses http://localhost:8000
    python demo/seed.py --api http://localhost:8000
    python demo/seed.py --skip-analysis          # upload only, no LLM analysis

Requirements:
    pip install httpx rich
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

try:
    import httpx
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.panel import Panel
    from rich.table import Table
except ImportError:
    print("Install dependencies: pip install httpx rich")
    sys.exit(1)

console = Console()
DEMO_DATA_DIR = Path(__file__).parent / "data"
API_BASE = "http://localhost:8000/api/v1"


def wait_for_backend(base_url: str, timeout: int = 60) -> bool:
    """Poll /health until backend is ready."""
    health_url = base_url.rstrip("/api/v1").rstrip("/") + "/health"
    console.print(f"[dim]Waiting for backend at {health_url}...[/dim]")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(health_url, timeout=3)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def upload_file(client: httpx.Client, filepath: Path) -> str | None:
    """Upload a CSV file, return job_id."""
    console.print(f"[cyan]↑[/cyan] Uploading [bold]{filepath.name}[/bold]...")
    with open(filepath, "rb") as f:
        resp = client.post(
            "/upload",
            files={"file": (filepath.name, f, "text/csv")},
            timeout=30,
        )
    if resp.status_code not in (200, 201):
        console.print(f"[red]✗ Upload failed:[/red] {resp.status_code} {resp.text[:200]}")
        return None

    data = resp.json().get("data") or resp.json()
    job_id = data.get("job_id")
    console.print(f"[green]✓[/green] Uploaded → job_id: [bold cyan]{job_id}[/bold cyan]")
    return job_id


def start_analysis(client: httpx.Client, job_id: str) -> bool:
    """Trigger analysis for a job."""
    resp = client.post(f"/analyze/{job_id}", timeout=10)
    return resp.status_code in (200, 201, 202)


def poll_job(client: httpx.Client, job_id: str, timeout: int = 120) -> dict | None:
    """Poll job status until completed or failed."""
    deadline = time.time() + timeout
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Analyzing financial data...", total=None)
        while time.time() < deadline:
            resp = client.get(f"/analysis/{job_id}", timeout=10)
            if resp.status_code != 200:
                time.sleep(2)
                continue
            data = resp.json().get("data") or resp.json()
            status = data.get("status", "")
            progress.update(task, description=f"Agent running: [bold]{status}[/bold]")

            if status == "completed":
                progress.update(task, description="[green]✓ Analysis complete![/green]")
                return data
            elif status == "failed":
                progress.update(task, description=f"[red]✗ Failed: {data.get('error')}[/red]")
                return None
            elif status == "awaiting_review":
                progress.update(task, description="[yellow]⚠ Awaiting human review — auto-approving for demo...[/yellow]")
                # Auto-approve for demo
                client.post(f"/analysis/{job_id}/approve", timeout=10)

            time.sleep(3)
    return None


def fetch_dashboard(client: httpx.Client, job_id: str) -> dict | None:
    """Fetch dashboard summary."""
    resp = client.get(f"/dashboard/{job_id}", timeout=15)
    if resp.status_code == 200:
        return (resp.json().get("data") or resp.json())
    return None


def print_summary(dashboard: dict, job_id: str) -> None:
    """Print a rich summary of the analysis results."""
    pnl = dashboard.get("pnl", {})
    cf  = dashboard.get("cashflow", {})
    fc  = dashboard.get("forecast", {})
    tx_count = dashboard.get("transaction_count", 0)

    console.print()
    console.print(Panel.fit(
        "[bold green]✓ Demo Analysis Complete![/bold green]\n"
        f"[dim]job_id: {job_id}[/dim]",
        border_style="green",
    ))

    # Financial summary table
    table = Table(title="TechNova Yazılım A.Ş. — 2024 Financial Summary", show_header=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right", style="cyan")

    def fmt(v: float) -> str:
        if abs(v) >= 1_000_000:
            return f"₺{v/1_000_000:.2f}M"
        if abs(v) >= 1_000:
            return f"₺{v/1_000:.1f}K"
        return f"₺{v:.0f}"

    table.add_row("Revenue",        fmt(pnl.get("revenue", 0)))
    table.add_row("Gross Profit",   fmt(pnl.get("gross_profit", 0)))
    table.add_row("Gross Margin",   f"{pnl.get('gross_margin', 0)*100:.1f}%")
    table.add_row("EBITDA",         fmt(pnl.get("ebitda", 0)))
    table.add_row("Net Income",     fmt(pnl.get("net_income", 0)))
    table.add_row("Net Margin",     f"{pnl.get('net_margin', 0)*100:.1f}%")
    table.add_row("Net Cash Flow",  fmt(cf.get("net_change", 0)))

    base = (fc.get("scenarios") or {}).get("base", {})
    if base.get("runway_months"):
        table.add_row("Cash Runway", f"{base['runway_months']} months")

    table.add_row("Transactions Analyzed", str(tx_count))
    console.print(table)

    # Alerts
    alerts = (cf.get("alerts") or []) + (fc.get("alerts") or [])
    if alerts:
        console.print("\n[bold yellow]⚠ Alerts[/bold yellow]")
        for a in alerts[:5]:
            icon = "🔴" if a.get("level") == "critical" else "🟡"
            console.print(f"  {icon} {a.get('message', '')[:100]}")

    console.print(f"\n[bold]→ Open dashboard:[/bold] [link=http://localhost:3000/?job={job_id}]http://localhost:3000/?job={job_id}[/link]")
    console.print(f"[bold]→ API docs:[/bold] [link=http://localhost:8000/docs]http://localhost:8000/docs[/link]")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI CFO Suite demo seeder")
    parser.add_argument("--api",             default=API_BASE,    help="Backend API base URL")
    parser.add_argument("--skip-analysis",   action="store_true", help="Upload only, skip LLM analysis")
    parser.add_argument("--file",            default="logo_tiger_2024.csv", help="CSV file in demo/data/")
    args = parser.parse_args()

    console.print(Panel.fit(
        "[bold cyan]AI CFO Suite — Demo Setup[/bold cyan]\n"
        "[dim]TechNova Yazılım A.Ş. — 12 months of financial data[/dim]",
        border_style="cyan",
    ))

    # Wait for backend
    if not wait_for_backend(args.api):
        console.print("[red]✗ Backend not reachable. Run: docker-compose up[/red]")
        sys.exit(1)

    console.print("[green]✓ Backend is ready[/green]")

    filepath = DEMO_DATA_DIR / args.file
    if not filepath.exists():
        console.print(f"[red]✗ File not found: {filepath}[/red]")
        sys.exit(1)

    with httpx.Client(base_url=args.api) as client:
        # Upload
        job_id = upload_file(client, filepath)
        if not job_id:
            sys.exit(1)

        if args.skip_analysis:
            console.print(f"\n[yellow]Skipping analysis (--skip-analysis)[/yellow]")
            console.print(f"job_id: [bold]{job_id}[/bold]")
            return

        # Start analysis
        console.print("[cyan]⚡[/cyan] Starting AI agent pipeline...")
        ok = start_analysis(client, job_id)
        if not ok:
            console.print("[yellow]⚠ Could not start analysis (no LLM key?) — job_id saved[/yellow]")
            console.print(f"[dim]You can still view the uploaded data at /?job={job_id}[/dim]")
            return

        # Poll until done
        result = poll_job(client, job_id)
        if not result:
            console.print("[yellow]⚠ Analysis did not complete (no LLM key or timeout)[/yellow]")
            console.print(f"[dim]Dashboard URL: http://localhost:3000/?job={job_id}[/dim]")
            return

        # Fetch and print summary
        dashboard = fetch_dashboard(client, job_id)
        if dashboard:
            print_summary(dashboard, job_id)
        else:
            console.print(f"[green]✓ Done![/green] job_id: [bold]{job_id}[/bold]")
            console.print(f"[dim]Dashboard: http://localhost:3000/?job={job_id}[/dim]")


if __name__ == "__main__":
    main()
