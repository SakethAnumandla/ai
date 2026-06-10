# routers/__init__.py
from .expenses import router as expenses_router
from .ocr import router as ocr_router
from .wallet import router as wallet_router
from .dashboard import router as dashboard_router

# Export all routers
__all__ = [
    "expenses_router",
    "ocr_router", 
    "wallet_router",
    "dashboard_router"
]