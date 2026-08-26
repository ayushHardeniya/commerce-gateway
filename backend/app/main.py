from fastapi import FastAPI

from app.agents.router import router as agent_router
from app.api.health import router as health_router
from app.catalog.router import router as catalog_router
from app.commerce.cart.router import router as cart_router
from app.commerce.checkout.router import router as checkout_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.include_router(health_router)
app.include_router(catalog_router)
app.include_router(cart_router)
app.include_router(checkout_router)
app.include_router(agent_router)
