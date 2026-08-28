from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.router import router as agent_router
from app.api.health import router as health_router
from app.catalog.router import router as catalog_router
from app.commerce.cart.router import router as cart_router
from app.commerce.checkout.router import router as checkout_router
from app.commerce.payment.router import router as payment_router
from app.commerce.policy.router import router as policy_router
from app.commerce.transaction.router import router as transaction_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)

# Lets the local Next.js dev server (a different origin) call this API from
# the browser. No credentials (cookies/auth headers) are shared across
# origins by this app, so allow_credentials stays False; origins are never
# a wildcard and come only from Settings.cors_allowed_origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(catalog_router)
app.include_router(cart_router)
app.include_router(checkout_router)
app.include_router(policy_router)
app.include_router(payment_router)
app.include_router(transaction_router)
app.include_router(agent_router)
