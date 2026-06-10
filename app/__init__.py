# app/__init__.py
"""
Expense Tracker Management System
A comprehensive expense tracking solution with OCR capabilities
"""

__version__ = "1.0.0"
__author__ = "Expense Tracker Team"
__description__ = "Track expenses with manual entry and OCR scanning"

# Import main app components
from app.main import app
from app.database import Base, engine, get_db
from app.config import settings

# Export commonly used items
__all__ = [
    "app",
    "Base",
    "engine", 
    "get_db",
    "settings",
    "__version__"
]