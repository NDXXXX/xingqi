"""统一 API 错误响应。"""

import logging

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def classify_provider_error(exc: Exception) -> tuple[str, str, bool, int]:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {401, 403}:
            return "PROVIDER_AUTH_FAILED", "Provider API Key 无效或无权限", False, 502
        if status == 429:
            return "PROVIDER_RATE_LIMITED", "Provider 请求频率受限，请稍后重试", True, 429
        return "PROVIDER_UNAVAILABLE", f"Provider 请求失败（HTTP {status}）", True, 502
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "PROVIDER_UNAVAILABLE", "Provider 请求超时", True, 504
    return "INTERNAL_ERROR", str(exc) or "内部错误", False, 500


def _payload(request: Request, code: str, message: str, retryable: bool = False) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "request_id": getattr(request.state, "request_id", None),
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(httpx.HTTPError)
    async def provider_error(request: Request, exc: httpx.HTTPError) -> JSONResponse:
        code, message, retryable, status = classify_provider_error(exc)
        return JSONResponse(
            status_code=status,
            content=_payload(request, code, message, retryable),
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        code = {
            400: "VALIDATION_ERROR",
            404: "NOT_FOUND",
            409: "CONFLICT",
            429: "PROVIDER_RATE_LIMITED",
        }.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(request, code, str(exc.detail), exc.status_code in {429, 502, 503, 504}),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        message = "; ".join(
            f"{'.'.join(str(item) for item in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        return JSONResponse(
            status_code=422,
            content=_payload(request, "VALIDATION_ERROR", message),
        )

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled request error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_payload(request, "INTERNAL_ERROR", "内部错误", retryable=True),
        )
