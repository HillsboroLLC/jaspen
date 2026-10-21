import uuid
from datetime import datetime

from app import db


class PlanBuildJob(db.Model):
    """One execution-plan build running in the background.

    The request that starts a build returns at once; the work, its result, and
    the response the client eventually receives are kept here so a status
    check from any worker can report it, or restart it after an interruption.
    """

    __tablename__ = "plan_build_jobs"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    thread_id = db.Column(db.String(255), nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, default="running", server_default="running")
    request_json = db.Column(db.JSON, nullable=False, default=dict)
    result_json = db.Column(db.JSON, nullable=True)
    result_status = db.Column(db.Integer, nullable=True)
    run_count = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    heartbeat_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)
