import os
import re
from typing import Optional

from backend.core.security import DEFAULT_ADMIN_EMAIL, PROJECT_ROOT, is_within

ACCOUNTS_ROOT = os.path.join(PROJECT_ROOT, "Accounts")


def sanitize_email(email: str) -> str:
    """Maps an email to a filesystem-safe folder name (e.g. a.b@x.io -> a_b_x_io)."""
    return re.sub(r"[^a-z0-9_\-]", "_", email.strip().lower())


def get_user_dir(email: str = None) -> Optional[str]:
    """
    Returns the absolute path to a user-specific Accounts folder.
    If no email is provided, returns None to indicate root workspace directories.
    """
    if not email:
        return None
    user_dir = os.path.join(ACCOUNTS_ROOT, sanitize_email(email))
    os.makedirs(user_dir, exist_ok=True)
    return user_dir


def get_user_path(email: str, relative_path: str) -> str:
    """
    Resolves a relative path (e.g. 'data/raw/dataset.csv') inside the user's Accounts directory.
    If email is None, resolves inside the root project directory.
    Ensures parent directories exist and that the result cannot escape the base directory.
    """
    base_dir = get_user_dir(email) or PROJECT_ROOT
    full_path = os.path.abspath(os.path.join(base_dir, relative_path))
    if not is_within(full_path, base_dir):
        raise ValueError(f"Path '{relative_path}' escapes the workspace directory.")
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    return full_path.replace("\\", "/")


def is_admin(email: Optional[str]) -> bool:
    return (email or "").strip().lower() == DEFAULT_ADMIN_EMAIL


def is_path_accessible(path: str, email: Optional[str]) -> bool:
    """
    A user may access files inside their own Accounts folder. The administrator may additionally
    access the shared root workspace folders (used by CLI / SnapLogic runs without an account).
    """
    user_dir = get_user_dir(email)
    if user_dir and is_within(path, user_dir):
        return True
    if is_admin(email) or not email:
        for folder in ["data", "cleaned data", "reports", "logs"]:
            if is_within(path, os.path.join(PROJECT_ROOT, folder)):
                return True
    return False


def resolve_project_path(path: str) -> str:
    """Resolves a relative path against the project root, leaving absolute paths untouched."""
    if not path:
        return ""
    if os.path.isabs(path):
        return os.path.abspath(path)
    return os.path.abspath(os.path.join(PROJECT_ROOT, path))


def user_owns_batch(db, batch_id: str, email: Optional[str]) -> bool:
    """True if the batch was uploaded by this user (admin may inspect every batch)."""
    from sqlalchemy import text
    if not batch_id:
        return False
    if is_admin(email):
        return True
    owner_row = db.execute(
        text("SELECT uploaded_by FROM raw_uploads WHERE batch_id = :b LIMIT 1"), {"b": batch_id}
    ).first()
    return bool(owner_row) and owner_row[0] == email


def get_user_batch_ids(db, email: Optional[str]) -> list:
    from sqlalchemy import text
    rows = db.execute(
        text("SELECT batch_id FROM raw_uploads WHERE uploaded_by = :e"), {"e": email}
    ).fetchall()
    return [r[0] for r in rows if r[0]]
