from fastapi import FastAPI, status
from fastapi.exceptions import RequestValidationError
from fastapi_prometheus_metrics.endpoints import router as metrics_router
from fastapi_prometheus_metrics.manager import PrometheusManager
from fastapi_prometheus_metrics.middleware import MetricsSecurityMiddleware, PrometheusMiddleware
from starlette.exceptions import HTTPException

from cosmos.accounts.api.endpoints.account import bpl_operations_router
from cosmos.accounts.api.endpoints.account import router as account_router
from cosmos.accounts.api.endpoints.enrolment import router as enrolment_router
from cosmos.core.api.exception_handlers import (
    http_exception_handler,
    payload_request_validation_error,
    request_validation_handler,
    service_error_handler,
    unexpected_exception_handler,
)
from cosmos.core.api.exceptions import RequestPayloadValidationError
from cosmos.core.api.healthz import healthz_router
from cosmos.core.api.service import ServiceError


def create_app() -> FastAPI:
    fapi = FastAPI(title="Account Management API")
    fapi.include_router(healthz_router)
    fapi.include_router(enrolment_router)
    fapi.include_router(account_router)
    fapi.include_router(bpl_operations_router)
    fapi.include_router(metrics_router)
    fapi.add_exception_handler(RequestValidationError, request_validation_handler)
    fapi.add_exception_handler(RequestPayloadValidationError, payload_request_validation_error)
    fapi.add_exception_handler(HTTPException, http_exception_handler)
    fapi.add_exception_handler(ServiceError, service_error_handler)
    fapi.add_exception_handler(status.HTTP_500_INTERNAL_SERVER_ERROR, unexpected_exception_handler)

    fapi.add_middleware(MetricsSecurityMiddleware)
    fapi.add_middleware(PrometheusMiddleware)

    PrometheusManager("accounts", metric_name_prefix="bpl")  # initialise signals

    # Prevent 307 temporary redirects if URLs have slashes on the end
    fapi.router.redirect_slashes = False

    return fapi


app = create_app()
