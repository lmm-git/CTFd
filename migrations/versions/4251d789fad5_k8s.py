"""empty message

Revision ID: 4251d789fad5
Revises: f70c6e87efbe
Create Date: 2021-03-31 22:13:16.728556

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4251d789fad5'
down_revision = 'f70c6e87efbe'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('challenges', sa.Column('kubernetes_description', sa.Text(), nullable=True))
    op.add_column('challenges', sa.Column('kubernetes_enabled', sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column('challenges', 'kubernetes_enabled')
    op.drop_column('challenges', 'kubernetes_description')
