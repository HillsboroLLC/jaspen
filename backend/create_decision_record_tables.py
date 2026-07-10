# backend/create_decision_record_tables.py
#
# One-off, idempotent setup for canonical Decision Record storage.
# Creates the additive `decision_records` table if it doesn't already exist.
# SAFE: db.create_all() only creates missing tables — it never alters, drops,
# or touches existing tables or data.
#
# This script remains a local-development convenience for quickly ensuring the
# table exists. Production deployments should use the Alembic migration for the
# canonical schema path.
#
# Run from backend/ with the venv active:
#   python create_decision_record_tables.py

from app import create_app, db
from app import models_decision_record  # noqa: F401  registers DecisionRecord

app = create_app()
with app.app_context():
    inspector = db.inspect(db.engine)
    before = set(inspector.get_table_names())
    db.create_all()
    after = set(db.inspect(db.engine).get_table_names())
    created = sorted(after - before)
    print("Newly created tables:", created or "(none — already existed)")
    print(f"  decision_records: {'present ✓' if 'decision_records' in after else 'MISSING ✗'}")
