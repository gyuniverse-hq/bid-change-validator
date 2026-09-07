from fastapi import Depends, FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .errors import ApiError
from .qualification_analysis_router import router as qualification_analysis_router
from .qualification_ask_back_router import router as qualification_ask_back_router
from .qualification_judgment_router import router as qualification_judgment_router
from .qualification_revalidation_router import router as qualification_revalidation_router
from .routers.companies import router as companies_router
from .routers.master_codes import router as master_codes_router
from .routers.notices import router as notices_router
from .routers.preflight_cases import router as preflight_cases_router


settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Length", "Content-Type", "ETag"],
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


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_request, error: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "INVALID_REQUEST",
                "message": "요청 형식이 올바르지 않습니다.",
                "details": jsonable_encoder(error.errors()),
            }
        },
    )


@app.get("/health", tags=["system"])
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


app.include_router(companies_router)
app.include_router(master_codes_router)
app.include_router(notices_router)
app.include_router(preflight_cases_router)
app.include_router(qualification_analysis_router)
app.include_router(qualification_judgment_router)
app.include_router(qualification_ask_back_router)
app.include_router(qualification_revalidation_router)
