"""Initial schema

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Table: services
    # ------------------------------------------------------------------
    op.create_table(
        'services',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('swagger_url', sa.String(1024), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('swagger_version', sa.String(50), nullable=True),
        sa.Column('base_url', sa.String(1024), nullable=True),
        sa.Column('last_scanned_at', sa.DateTime(), nullable=True),
        sa.Column('scan_status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('scan_error', sa.Text(), nullable=True),
        sa.Column('ai_overview', sa.Text(), nullable=True),
        sa.Column('ai_use_cases', sa.Text(), nullable=True),
        sa.Column('ai_documentation_score', sa.Integer(), nullable=True),
        sa.Column('ai_documentation_notes', sa.Text(), nullable=True),
        sa.Column('ai_analyzed_at', sa.DateTime(), nullable=True),
        sa.Column('auth_type', sa.String(50), nullable=True),
        sa.Column('ai_design_score', sa.Integer(), nullable=True),
        sa.Column('ai_design_recommendations', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('swagger_url', name='uq_services_swagger_url'),
    )

    # ------------------------------------------------------------------
    # Table: endpoints
    # ------------------------------------------------------------------
    op.create_table(
        'endpoints',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('service_id', sa.Integer(), nullable=False),
        sa.Column('path', sa.String(1024), nullable=False),
        sa.Column('method', sa.String(10), nullable=False),
        sa.Column('summary', sa.String(500), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('parameters_json', sa.Text(), nullable=True),
        sa.Column('request_body_json', sa.Text(), nullable=True),
        sa.Column('response_json', sa.Text(), nullable=True),
        sa.Column('tags', sa.String(500), nullable=True),
        sa.Column('deprecated', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('ai_summary', sa.Text(), nullable=True),
        sa.Column('ai_request_example', sa.Text(), nullable=True),
        sa.Column('ai_response_example', sa.Text(), nullable=True),
        sa.Column('ai_use_cases', sa.Text(), nullable=True),
        sa.Column('ai_notes', sa.Text(), nullable=True),
        sa.Column('auth_required', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['service_id'], ['services.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_endpoints_service_id', 'endpoints', ['service_id'])

    # ------------------------------------------------------------------
    # Table: scan_logs
    # ------------------------------------------------------------------
    op.create_table(
        'scan_logs',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('service_id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(50), nullable=True),
        sa.Column('endpoints_found', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['service_id'], ['services.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_scan_logs_service_id', 'scan_logs', ['service_id'])


def downgrade() -> None:
    op.drop_index('ix_scan_logs_service_id', table_name='scan_logs')
    op.drop_table('scan_logs')
    op.drop_index('ix_endpoints_service_id', table_name='endpoints')
    op.drop_table('endpoints')
    op.drop_table('services')
