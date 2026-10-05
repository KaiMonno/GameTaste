"""phase 7: add owned_platforms to user_preferences

Revision ID: 4118f2cd1ae0
Revises: 29457369f226
Create Date: 2026-10-05 00:41:35.175651

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '4118f2cd1ae0'
down_revision: Union[str, None] = '29457369f226'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Autogenerate emitted nullable=False with no server_default, which
    # fails outright against any existing row (NOT NULL violation) -
    # user_preferences already has real rows from Phase 5 testing. '{}' is
    # the empty-array literal, matching the model's default=list.
    op.add_column(
        'user_preferences',
        sa.Column('owned_platforms', postgresql.ARRAY(sa.String()), nullable=False, server_default='{}'),
    )


def downgrade() -> None:
    op.drop_column('user_preferences', 'owned_platforms')
