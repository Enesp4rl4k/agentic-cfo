"""
Locust load testing scenario for Agentic CFO Platform.

Simulates realistic user behavior across all critical endpoints:
- Auth (login, token refresh)
- File upload → CFO pipeline
- Dashboard polling
- Chat interaction
- CEO synthesis
- Kernel API calls (CTO/CMO/CHRO/COO)
- Analytics (Monte Carlo, working capital, etc.)

Usage:
    # Install locust first
    pip install locust

    # Run with web UI
    locust -f backend/locustfile.py --host=http://localhost:8000

    # Headless with 50 users, 5/sec spawn rate, 5 min duration
    locust -f backend/locustfile.py --host=http://localhost:8000 \
           --users 50 --spawn-rate 5 --run-time 5m --headless

    # With HTML report
    locust -f backend/locustfile.py --host=http://localhost:8000 \
           --users 100 --spawn-rate 10 --run-time 10m --headless \
           --html report.html
"""

import random
import time
from typing import Any

from locust import HttpUser, TaskSet, between, task


class AuthBehavior(TaskSet):
    """User authentication and session management."""

    def on_start(self) -> None:
        """Login and store tokens."""
        # Use test credentials (ensure test user exists in DB)
        response = self.client.post(
            "/auth/login",
            json={
                "email": f"loadtest+{random.randint(1, 100)}@example.com",
                "password": "TestPassword123!",
            },
            name="/auth/login",
        )

        if response.status_code == 200:
            data = response.json()
            self.user.access_token = data.get("access_token", "")
            self.user.refresh_token = data.get("refresh_token", "")
            self.user.org_id = data.get("user", {}).get("org_id")
        else:
            # Fallback: register new user
            reg_response = self.client.post(
                "/auth/register",
                json={
                    "email": f"loadtest+{random.randint(1000, 9999)}@example.com",
                    "password": "TestPassword123!",
                    "full_name": "Load Test User",
                },
                name="/auth/register",
            )
            if reg_response.status_code == 201:
                data = reg_response.json()
                self.user.access_token = data.get("access_token", "")
                self.user.org_id = data.get("user", {}).get("org_id")

    def headers(self) -> dict[str, str]:
        """Return auth headers."""
        return {"Authorization": f"Bearer {self.user.access_token}"}

    @task(1)
    def refresh_token(self) -> None:
        """Refresh access token."""
        if not hasattr(self.user, "refresh_token"):
            return

        response = self.client.post(
            "/auth/refresh",
            json={"refresh_token": self.user.refresh_token},
            name="/auth/refresh",
        )

        if response.status_code == 200:
            data = response.json()
            self.user.access_token = data.get("access_token", "")


class CFOPipelineBehavior(TaskSet):
    """CFO pipeline: upload → poll → dashboard → reports."""

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.user.access_token}"}

    @task(5)
    def upload_file(self) -> None:
        """Upload a CSV file and start CFO analysis."""
        # Generate minimal CSV data
        csv_content = (
            "date,description,amount,category\n"
            "2024-01-15,Office supplies,-1250.00,OpEx\n"
            "2024-01-20,Client payment A,15000.00,Revenue\n"
            "2024-01-25,Salary payment,-8500.00,Personnel\n"
        )

        files = {"file": ("test_transactions.csv", csv_content, "text/csv")}

        response = self.client.post(
            "/upload",
            files=files,
            headers=self.headers(),
            name="/upload",
        )

        if response.status_code == 200:
            data = response.json()
            self.user.active_job_id = data.get("job_id")

    @task(10)
    def poll_job_status(self) -> None:
        """Poll job status."""
        if not hasattr(self.user, "active_job_id"):
            return

        self.client.get(
            f"/jobs/{self.user.active_job_id}/status",
            headers=self.headers(),
            name="/jobs/{job_id}/status",
        )

    @task(8)
    def get_dashboard(self) -> None:
        """Fetch dashboard data."""
        if not hasattr(self.user, "active_job_id"):
            return

        self.client.get(
            f"/dashboard/{self.user.active_job_id}",
            headers=self.headers(),
            name="/dashboard/{job_id}",
        )

    @task(3)
    def list_reports(self) -> None:
        """List generated reports."""
        if not hasattr(self.user, "active_job_id"):
            return

        self.client.get(
            f"/reports/{self.user.active_job_id}",
            headers=self.headers(),
            name="/reports/{job_id}",
        )

    @task(2)
    def list_jobs(self) -> None:
        """List all user jobs."""
        self.client.get(
            "/jobs",
            headers=self.headers(),
            name="/jobs",
        )


class ChatBehavior(TaskSet):
    """Chat and natural language query."""

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.user.access_token}"}

    @task(5)
    def send_chat_message(self) -> None:
        """Send a chat message (non-streaming for simplicity)."""
        if not hasattr(self.user, "active_job_id"):
            return

        questions = [
            "Nakit akışım nasıl?",
            "En büyük gider kalemim nedir?",
            "Önümüzdeki ay için tahmin ne?",
            "Anomali var mı?",
            "OPEX optimizasyonu öner",
        ]

        self.client.post(
            f"/chat/job/{self.user.active_job_id}",
            json={"question": random.choice(questions)},
            headers=self.headers(),
            name="/chat/job/{job_id}",
        )


class KernelBehavior(TaskSet):
    """C-Suite kernel API calls."""

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.user.access_token}"}

    @task(2)
    def cto_kernel(self) -> None:
        """Request CTO kernel analysis."""
        if not hasattr(self.user, "active_job_id"):
            return

        self.client.post(
            "/kernels/cto/from-job",
            json={"job_id": self.user.active_job_id},
            headers=self.headers(),
            name="/kernels/cto/from-job",
        )

    @task(2)
    def cmo_kernel(self) -> None:
        """Request CMO kernel analysis."""
        if not hasattr(self.user, "active_job_id"):
            return

        self.client.post(
            "/kernels/cmo/from-job",
            json={"job_id": self.user.active_job_id},
            headers=self.headers(),
            name="/kernels/cmo/from-job",
        )

    @task(1)
    def chro_kernel(self) -> None:
        """Request CHRO kernel analysis."""
        if not hasattr(self.user, "org_id"):
            return

        self.client.post(
            "/kernels/chro/from-org",
            json={"org_id": self.user.org_id, "sector": "saas"},
            headers=self.headers(),
            name="/kernels/chro/from-org",
        )

    @task(1)
    def coo_kernel(self) -> None:
        """Request COO kernel analysis."""
        if not hasattr(self.user, "org_id"):
            return

        self.client.post(
            "/kernels/coo/from-org",
            json={"org_id": self.user.org_id},
            headers=self.headers(),
            name="/kernels/coo/from-org",
        )


class AnalyticsBehavior(TaskSet):
    """Advanced analytics endpoints."""

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.user.access_token}"}

    @task(3)
    def monte_carlo(self) -> None:
        """Run Monte Carlo cash flow simulation."""
        self.client.post(
            "/analytics/monte-carlo",
            json={
                "current_cash": 50000,
                "monthly_revenue_mean": 20000,
                "monthly_revenue_std": 3000,
                "monthly_cost_mean": 15000,
                "monthly_cost_std": 2000,
                "months": 12,
                "simulations": 1000,
                "bankruptcy_threshold": 5000,
            },
            headers=self.headers(),
            name="/analytics/monte-carlo",
        )

    @task(2)
    def working_capital(self) -> None:
        """Analyze working capital."""
        self.client.post(
            "/analytics/working-capital",
            json={
                "revenue_annual": 500000,
                "cogs_annual": 300000,
                "accounts_receivable": 40000,
                "accounts_payable": 25000,
                "inventory": 15000,
                "sector": "saas",
            },
            headers=self.headers(),
            name="/analytics/working-capital",
        )

    @task(1)
    def break_even(self) -> None:
        """Calculate break-even analysis."""
        self.client.post(
            "/analytics/break-even",
            json={
                "fixed_costs_monthly": 10000,
                "variable_cost_per_unit": 50,
                "price_per_unit": 100,
                "current_units": 250,
            },
            headers=self.headers(),
            name="/analytics/break-even",
        )

    @task(1)
    def get_macro(self) -> None:
        """Fetch macro economic snapshot."""
        self.client.get(
            "/analytics/macro",
            headers=self.headers(),
            name="/analytics/macro",
        )


class CEOBehavior(TaskSet):
    """CEO synthesis and board deck."""

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.user.access_token}"}

    @task(1)
    def enqueue_ceo_analysis(self) -> None:
        """Start CEO synthesis."""
        if not hasattr(self.user, "active_job_id"):
            return

        response = self.client.post(
            "/ceo/analyze",
            json={"job_id": self.user.active_job_id},
            headers=self.headers(),
            name="/ceo/analyze",
        )

        if response.status_code == 200:
            data = response.json()
            self.user.ceo_job_id = data.get("ceo_job_id")

    @task(2)
    def poll_ceo_status(self) -> None:
        """Poll CEO job status."""
        if not hasattr(self.user, "ceo_job_id"):
            return

        self.client.get(
            f"/ceo/status/{self.user.ceo_job_id}",
            headers=self.headers(),
            name="/ceo/status/{ceo_job_id}",
        )


class AgenticCFOUser(HttpUser):
    """Simulated user with mixed behavior."""

    wait_time = between(2, 8)  # Wait 2-8 seconds between tasks

    # Weight distribution across task sets
    tasks = {
        CFOPipelineBehavior: 40,  # 40% of time on core CFO pipeline
        ChatBehavior: 25,  # 25% on chat/queries
        AnalyticsBehavior: 15,  # 15% on analytics
        KernelBehavior: 10,  # 10% on kernel APIs
        CEOBehavior: 5,  # 5% on CEO synthesis
        AuthBehavior: 5,  # 5% on auth operations
    }

    def on_start(self) -> None:
        """Initialize user session."""
        # Register or login
        email = f"loadtest+{random.randint(1, 100)}@example.com"
        password = "TestPassword123!"

        # Try login first
        response = self.client.post(
            "/auth/login",
            json={"email": email, "password": password},
            name="/auth/login (on_start)",
        )

        if response.status_code == 200:
            data = response.json()
            self.access_token = data.get("access_token", "")
            self.refresh_token = data.get("refresh_token", "")
            self.org_id = data.get("user", {}).get("org_id")
        else:
            # Register new user
            reg_response = self.client.post(
                "/auth/register",
                json={
                    "email": f"loadtest+{random.randint(1000, 99999)}@example.com",
                    "password": password,
                    "full_name": f"Load Test User {random.randint(1, 1000)}",
                },
                name="/auth/register (on_start)",
            )

            if reg_response.status_code == 201:
                data = reg_response.json()
                self.access_token = data.get("access_token", "")
                self.org_id = data.get("user", {}).get("org_id")
