"""enforce immutable ledger entries

Revision ID: 0002_ledger_immutability
Revises: 0001_ledger
Create Date: 2026-02-18
"""

from alembic import op


revision = "0002_ledger_immutability"
down_revision = "0001_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_ledger_entry_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'ledger_entries is append-only; % is not allowed', TG_OP;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_ledger_entries_immutable
        BEFORE UPDATE OR DELETE ON ledger_entries
        FOR EACH ROW
        EXECUTE FUNCTION prevent_ledger_entry_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_ledger_entries_immutable ON ledger_entries;")
    op.execute("DROP FUNCTION IF EXISTS prevent_ledger_entry_mutation();")
