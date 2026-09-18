"""Four tables the models use and no migration created.

alert_preferences, in_app_notifications, agent_jobs, smmm_onay_kayitlari:
SQLite databases got them from create_all, so every local run and test had
them; a Postgres database built by migrations never did, so SMMM approvals,
in-app notifications, agent jobs and alert preferences would have failed
there. Found by the first `alembic check` against Postgres in CI.

Generated from the models with alembic's autogenerate renderer; each table is
skipped where it already exists (databases created with create_all).

Revision ID: 037_missing_tables
Revises: 036_email_ingest
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "037_missing_tables"
down_revision = "036_email_ingest"
branch_labels = None
depends_on = None

_TABLES = ("alert_preferences", "in_app_notifications", "agent_jobs", "smmm_onay_kayitlari")


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if 'alert_preferences' not in tables:
        op.create_table('alert_preferences',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('channels', sa.Text(), nullable=False),
        sa.Column('min_severity', sa.String(length=20), nullable=False),
        sa.Column('slack_webhook_url', sa.String(length=500), nullable=True),
        sa.Column('slack_channel', sa.String(length=100), nullable=True),
        sa.Column('email_recipients', sa.Text(), nullable=True),
        sa.Column('whatsapp_number', sa.String(length=30), nullable=True),
        sa.Column('daily_digest_enabled', sa.Boolean(), nullable=False),
        sa.Column('digest_hour_utc', sa.Integer(), nullable=False),
        sa.Column('quiet_hours_start', sa.Integer(), nullable=True),
        sa.Column('quiet_hours_end', sa.Integer(), nullable=True),
        sa.Column('escalation_only', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_alert_preferences_org_id'), 'alert_preferences', ['org_id'], unique=True)

    if 'in_app_notifications' not in tables:
        op.create_table('in_app_notifications',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('level', sa.String(length=20), nullable=False),
        sa.Column('domain', sa.String(length=50), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('source', sa.String(length=100), nullable=False),
        sa.Column('job_id', sa.String(length=36), nullable=True),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('priority_score', sa.Float(), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_in_app_notifications_created_at'), 'in_app_notifications', ['created_at'], unique=False)
        op.create_index(op.f('ix_in_app_notifications_org_id'), 'in_app_notifications', ['org_id'], unique=False)

    if 'agent_jobs' not in tables:
        op.create_table('agent_jobs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('agent_type', sa.String(length=30), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('org_id', sa.String(length=36), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('input_data', sa.JSON(), nullable=True),
        sa.Column('result_json', sa.JSON(), nullable=True),
        sa.Column('logs', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('progress', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_agent_jobs_agent_type'), 'agent_jobs', ['agent_type'], unique=False)
        op.create_index(op.f('ix_agent_jobs_org_id'), 'agent_jobs', ['org_id'], unique=False)
        op.create_index(op.f('ix_agent_jobs_status'), 'agent_jobs', ['status'], unique=False)
        op.create_index(op.f('ix_agent_jobs_user_id'), 'agent_jobs', ['user_id'], unique=False)

    if 'smmm_onay_kayitlari' not in tables:
        op.create_table('smmm_onay_kayitlari',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('job_id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=True),
        sa.Column('created_by_user_id', sa.String(length=36), nullable=True),
        sa.Column('kayit_id', sa.String(length=36), nullable=False),
        sa.Column('orijinal_kayit', sa.JSON(), nullable=True),
        sa.Column('durum', sa.String(length=20), nullable=False),
        sa.Column('onaylayan_user_id', sa.String(length=36), nullable=True),
        sa.Column('onay_zamani', sa.DateTime(timezone=True), nullable=True),
        sa.Column('onay_notu', sa.Text(), nullable=True),
        sa.Column('duzeltilmis_hesap_kodu', sa.String(length=10), nullable=True),
        sa.Column('duzeltilmis_hesap_adi', sa.String(length=200), nullable=True),
        sa.Column('duzeltme_aciklama', sa.Text(), nullable=True),
        sa.Column('otomatik_hesap_kodu', sa.String(length=10), nullable=True),
        sa.Column('otomatik_confidence', sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column('otomatik_yontem', sa.String(length=20), nullable=True),
        sa.Column('onay_neden', sa.Text(), nullable=True),
        sa.Column('tx_description', sa.Text(), nullable=True),
        sa.Column('tx_amount_try', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('tx_tarih', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['analysis_jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_smmm_onay_kayitlari_durum'), 'smmm_onay_kayitlari', ['durum'], unique=False)
        op.create_index(op.f('ix_smmm_onay_kayitlari_job_id'), 'smmm_onay_kayitlari', ['job_id'], unique=False)
        op.create_index(op.f('ix_smmm_onay_kayitlari_kayit_id'), 'smmm_onay_kayitlari', ['kayit_id'], unique=False)
        op.create_index(op.f('ix_smmm_onay_kayitlari_org_id'), 'smmm_onay_kayitlari', ['org_id'], unique=False)


def downgrade() -> None:
    # Drops only what this revision created, in reverse order.
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for name in reversed(_TABLES):
        if name in tables:
            op.drop_table(name)
