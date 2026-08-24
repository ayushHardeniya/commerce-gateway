"""HTTP entry point for the AI buyer.

This exists to exercise the agent loop end-to-end (manual testing, smoke
checks) — it is not a production chat UI and holds no conversation history
across requests.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.buyer import (
    AgentConfigurationError,
    AgentIterationLimitExceeded,
    AgentProviderError,
    AIBuyerService,
)
from app.agents.schemas import AgentChatRequest, AgentChatResponse
from app.db.session import get_db

router = APIRouter(prefix="/api/agent", tags=["agent"])


def get_ai_buyer_service(db: Session = Depends(get_db)) -> AIBuyerService:
    return AIBuyerService(db)


@router.post("/chat", response_model=AgentChatResponse)
def chat(
    request: AgentChatRequest,
    service: AIBuyerService = Depends(get_ai_buyer_service),
) -> AgentChatResponse:
    try:
        return service.chat(request.message)
    except AgentConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AgentIterationLimitExceeded as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AgentProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
