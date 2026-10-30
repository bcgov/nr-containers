"""${message}

Revision ID: V${flyway_version}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Flyway-style versioning:
- V${flyway_version}: Versioned migration (immutable, executes once)
- R__${flyway_number}_*: Repeatable migration (can be re-executed)

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision = "V${flyway_version}"
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    """Upgrade migration - apply DDL changes."""
    pass
    ${upgrades if upgrades else "# TODO: Implement upgrade"}


def downgrade() -> None:
    """Downgrade migration - rollback DDL changes."""
    pass
    ${downgrades if downgrades else "# TODO: Implement downgrade"}
