import os

def get_user_dir(email: str = None) -> str:
    """
    Returns the absolute path to a user-specific Accounts folder.
    Sanitizes the email to ensure it is a safe folder name.
    If no email is provided, returns None to indicate root workspace directories.
    """
    if not email:
        return None
    
    # Sanitization: replace @ and . with underscores to be safe on all filesystems
    sanitized = email.replace("@", "_").replace(".", "_")
    
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    user_dir = os.path.join(PROJECT_ROOT, "Accounts", sanitized)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def get_user_path(email: str, relative_path: str) -> str:
    """
    Resolves a relative path (e.g. 'data/raw/dataset.csv') inside the user's Accounts directory.
    If email is None, resolves inside the root project directory.
    Ensures parent directories exist.
    """
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    user_dir = get_user_dir(email)
    
    if not user_dir:
        full_path = os.path.join(PROJECT_ROOT, relative_path)
    else:
        full_path = os.path.join(user_dir, relative_path)
        
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    return full_path.replace("\\", "/")
