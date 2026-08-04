import os
import shutil
from backend.database.mysql import Base, engine

def reset_workspace():
    print("=== RESETTING WORKSPACE TO A COMPLETELY FRESH CLEAN STATE ===")
    
    # 1. Clear active directories
    folders_to_clear = [
        "data/raw",
        "cleaned data",
        "reports",
        "logs"
    ]
    
    # 2. Redundant directories to completely remove
    folders_to_remove = [
        "data/csv",
        "data/word",
        "data/sql",
        "data/processed"
    ]
    
    for folder in folders_to_remove:
        if os.path.exists(folder):
            print(f"Removing redundant folder: {folder}")
            try:
                shutil.rmtree(folder)
            except Exception as e:
                print(f"Warning removing {folder}: {e}")

    for folder in folders_to_clear:
        if os.path.exists(folder):
            print(f"Clearing folder: {folder}")
            try:
                shutil.rmtree(folder)
            except Exception as e:
                print(f"Warning clearing {folder}: {e}")
        os.makedirs(folder, exist_ok=True)

    # 2. Reset database tables completely (Drops and re-creates empty schemas)
    print("Wiping and re-creating empty database tables...")
    try:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        print("Database tables reset successfully!")
    except Exception as e:
        print(f"Error resetting database: {e}")
        
    print("=== WORKSPACE HAS BEEN FULLY CLEANED AND RESET! ===")

if __name__ == "__main__":
    reset_workspace()
