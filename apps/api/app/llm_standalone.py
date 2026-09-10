"""LLM/RAG 라우터만 띄우는 단독 앱 — `main.py` 를 건드리지 않기 위한 것.

`qualification_briefing_router` 를 본 API 에 붙이려면 `main.py` 에 두 줄이 필요한데
그 파일은 Backend 소유라 손대지 않았다. 그래서 등록 전에도 동작을 확인할 수 있도록
같은 라우터만 물린 앱을 따로 둔다.

    uvicorn apps.api.app.llm_standalone:app --reload --port 8100
    http://localhost:8100/docs

본 API(`app.main`)와 **같은 DB, 같은 스키마, 같은 라우터**를 쓴다. 다른 코드 경로가
아니라 진입점만 다르다 — 여기서 동작하면 `main.py` 에 등록해도 그대로 동작한다.
라우터가 등록되고 나면 이 파일은 지워도 된다.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .errors import ApiError
from .qualification_briefing_router import router as qualification_briefing_router


settings = get_settings()

app = FastAPI(
    title=f"{settings.app_name} — LLM/RAG (standalone)",
    version=settings.app_version,
    description=(
        "공고 요약 · 판정 브리핑 · 챗봇 엔드포인트만 띄운 앱입니다. "
        "본 API에 라우터가 등록되면 이 앱은 필요 없습니다."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ApiError)
async def handle_api_error(_request, error: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "details": jsonable_encoder(error.details),
            }
        },
    )


@app.get("/health", tags=["system"])
def health() -> dict[str, object]:
    from .ai.providers.openai import OpenAINarrator, OpenAIStructuredExtractor

    return {
        "status": "ok",
        "llm_available": OpenAIStructuredExtractor().available,
        "narrator_available": OpenAINarrator().available,
    }


app.include_router(qualification_briefing_router)
