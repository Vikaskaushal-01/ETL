"""
Pytest bootstrap: runs the suite against a throwaway SQLite database with the offline LLM engine,
so tests never touch the developer's real database or call external LLM APIs.
Must execute before any `backend` module is imported, which is why it lives at the repo root.
"""
import os
import tempfile

_test_dir = tempfile.mkdtemp(prefix="etl_tests_")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_test_dir, 'test.db')}"
os.environ["LLM_PROVIDER"] = "mock"
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("PIPELINE_STEP_DELAY", "0")
os.environ.setdefault("PBI_REFRESH_DELAY", "0")


def pytest_sessionfinish(session, exitstatus):
    """Remove the account workspaces, logs and state files created by test runs from the project folders."""
    import shutil
    from sqlalchemy import text
    from backend.database.mysql import engine
    from backend.core.security import DEFAULT_ADMIN_EMAIL, PROJECT_ROOT
    from backend.utils.account_utils import ACCOUNTS_ROOT, sanitize_email

    try:
        with engine.connect() as conn:
            uploads = conn.execute(text("SELECT batch_id, filename FROM raw_uploads")).fetchall()
            emails = [r[0] for r in conn.execute(text("SELECT email FROM users")).fetchall()]
    except Exception:
        return
    batch_ids = {r[0] for r in uploads if r[0]}
    filenames = {r[1] for r in uploads if r[1]}

    for email in emails:
        if email != DEFAULT_ADMIN_EMAIL:
            shutil.rmtree(os.path.join(ACCOUNTS_ROOT, sanitize_email(email)), ignore_errors=True)

    def _belongs_to_test_batch(path: str) -> bool:
        name = os.path.basename(path)
        if any(bid in name for bid in batch_ids):
            return True
        # <filename>.log files are shared per file name, so check which batch wrote them
        if name.endswith(".log") and name[:-4] in filenames:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    head = f.read(4000)
                return any(bid in head for bid in batch_ids)
            except OSError:
                return False
        return False

    logs_dir = os.path.join(PROJECT_ROOT, "logs")
    for entry in os.listdir(logs_dir) if os.path.isdir(logs_dir) else []:
        path = os.path.join(logs_dir, entry)
        if os.path.isfile(path) and _belongs_to_test_batch(path):
            os.remove(path)

    reports_dir = os.path.join(PROJECT_ROOT, "reports")
    for folder in os.listdir(reports_dir) if os.path.isdir(reports_dir) else []:
        folder_path = os.path.join(reports_dir, folder)
        if not os.path.isdir(folder_path):
            continue
        removed_any = False
        for entry in os.listdir(folder_path):
            if _belongs_to_test_batch(os.path.join(folder_path, entry)):
                os.remove(os.path.join(folder_path, entry))
                removed_any = True
        if removed_any and not os.listdir(folder_path):
            os.rmdir(folder_path)
