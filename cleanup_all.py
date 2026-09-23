import os
import shutil
from backend.database.mysql import Base, engine

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))

# Tables that hold accounts and must survive a data reset
PRESERVED_TABLES = {"users"}


def _clear_folder(folder: str):
    os.makedirs(folder, exist_ok=True)
    print(f"Clearing folder: {folder}")
    # Entries are removed one by one so a file locked by the running server (e.g. the
    # platform log on Windows) does not stop the rest of the folder from being cleared.
    for entry in os.listdir(folder):
        path = os.path.join(folder, entry)
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        except Exception as e:
            print(f"Warning clearing {path}: {e}")


def reset_workspace():
    """
    Deletes all pipeline data (raw uploads, cleaned datasets, reports, logs, per-account
    workspaces) and empties every data table. User accounts are kept so people can still sign in.
    """
    print("=== RESETTING WORKSPACE TO A COMPLETELY FRESH CLEAN STATE ===")

    folders_to_clear = ["data/raw", "cleaned data", "reports", "logs", "Accounts"]
    # Legacy directories from older layouts that are removed entirely
    folders_to_remove = ["data/csv", "data/word", "data/sql", "data/processed"]

    for folder in folders_to_remove:
        path = os.path.join(PROJECT_ROOT, folder)
        if os.path.exists(path):
            print(f"Removing redundant folder: {path}")
            try:
                shutil.rmtree(path)
            except Exception as e:
                print(f"Warning removing {path}: {e}")

    for folder in folders_to_clear:
        _clear_folder(os.path.join(PROJECT_ROOT, folder))

    backup_path = os.path.join(PROJECT_ROOT, ".last_cleaned_backup.json")
    if os.path.exists(backup_path):
        os.remove(backup_path)

    print("Wiping and re-creating empty data tables (user accounts are preserved)...")
    try:
        data_tables = [t for t in Base.metadata.sorted_tables if t.name not in PRESERVED_TABLES]
        Base.metadata.drop_all(bind=engine, tables=data_tables)
        Base.metadata.create_all(bind=engine)
        print("Database tables reset successfully!")
    except Exception as e:
        print(f"Error resetting database: {e}")

    print("=== WORKSPACE HAS BEEN FULLY CLEANED AND RESET! ===")


if __name__ == "__main__":
    import backend.database.models  # noqa: F401 - registers all tables on Base.metadata
    reset_workspace()
