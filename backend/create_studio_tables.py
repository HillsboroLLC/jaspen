# backend/create_studio_tables.py
#
# One-off, idempotent setup for the new "Studio" storage.
# Creates the two additive tables (studio_workspaces, studio_artifacts) if they
# don't already exist. SAFE: db.create_all() only creates missing tables — it
# never alters, drops, or touches existing tables or data.
#
# Why not Flask-Migrate here? The migration history currently has multiple heads,
# which makes `flask db upgrade` ambiguous. Since these tables are purely additive,
# a targeted create_all sidesteps that mess without risk.
#
# Run from backend/ with the venv active:
#   python create_studio_tables.py

from app import create_app, db
from app import models_studio  # noqa: F401  registers StudioWorkspace / StudioArtifact

app = create_app()
with app.app_context():
    inspector = db.inspect(db.engine)
    before = set(inspector.get_table_names())
    db.create_all()
    after = set(db.inspect(db.engine).get_table_names())
    created = sorted(after - before)
    print("Newly created tables:", created or "(none — already existed)")
    for t in ("studio_workspaces", "studio_artifacts"):
        print(f"  {t}: {'present ✓' if t in after else 'MISSING ✗'}")
