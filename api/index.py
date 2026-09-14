import sys
from pathlib import Path

# Add root directory to sys.path so app module can be imported
sys.path.append(str(Path(__file__).parent.parent))

from app import Handler as handler, init_db

# Initialize database tables on serverless function load
try:
    init_db()
except Exception:
    pass
