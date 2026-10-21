from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
import math
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.config import OpenAISettings, get_settings, log_openai_configuration
from backend.app.routes import agent_router, cases_router, persistent_agent_router, review_router, screening_router
from backend.app.services.formulation_agent import FormulationAgentService, OpenAIFormulationInterpreter
from backend.app.services.loader import AcceptedBaselineError, RegulatoryStore, load_accepted_store
from backend.app.services.ingredient_catalog import (
    AcceptedIdentityCatalogueError,
    IngredientCatalog,
    load_accepted_ingredient_catalog,
)
from backend.app.services.source_rendering import IdentitySourceEvidenceRenderer, SourceEvidenceRenderer
from backend.app.services.review_explanations import ReviewExplanationService
from backend.app.services.supabase_gateway import SupabaseGateway


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, float):
        return value
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def create_app(
    store_loader: Callable[[], RegulatoryStore] = load_accepted_store,
    ingredient_catalog_loader: Callable[[], IngredientCatalog] = load_accepted_ingredient_catalog,
    formulation_agent_factory: Callable[[RegulatoryStore, IngredientCatalog | None], FormulationAgentService] | None = None,
    settings_loader: Callable[[], OpenAISettings] = get_settings,
    review_explanation_factory: Callable[[OpenAISettings], ReviewExplanationService] | None = None,
    supabase_gateway_factory: Callable[[OpenAISettings], SupabaseGateway] | None = None,
) -> FastAPI:
    settings = settings_loader()
    persistence_configured = settings.supabase_configured or supabase_gateway_factory is not None

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.regulatory_store = None
        application.state.source_evidence_renderer = None
        application.state.baseline_error = None
        application.state.ingredient_catalog = None
        application.state.identity_catalogue_error = None
        application.state.identity_source_evidence_renderer = None
        application.state.formulation_agent = None
        application.state.review_explanation_service = None
        application.state.supabase_gateway = None
        log_openai_configuration(settings)
        try:
            application.state.regulatory_store = store_loader()
            application.state.source_evidence_renderer = SourceEvidenceRenderer(
                application.state.regulatory_store
            )
        except AcceptedBaselineError as error:
            application.state.baseline_error = str(error)
        try:
            application.state.ingredient_catalog = ingredient_catalog_loader()
            application.state.identity_source_evidence_renderer = IdentitySourceEvidenceRenderer(
                application.state.ingredient_catalog
            )
        except AcceptedIdentityCatalogueError as error:
            application.state.identity_catalogue_error = str(error)
        if application.state.regulatory_store is not None:
            if formulation_agent_factory is None:
                application.state.formulation_agent = FormulationAgentService(
                    application.state.regulatory_store,
                    application.state.ingredient_catalog,
                    model_runner=OpenAIFormulationInterpreter(
                        api_key=settings.api_key,
                        timeout_seconds=settings.agent_timeout_seconds,
                    ),
                    model=settings.agent_model,
                )
            else:
                application.state.formulation_agent = formulation_agent_factory(
                    application.state.regulatory_store,
                    application.state.ingredient_catalog,
                )
        application.state.review_explanation_service = (
            review_explanation_factory(settings)
            if review_explanation_factory is not None
            else ReviewExplanationService(settings.api_key, settings.explanation_model)
        )
        if supabase_gateway_factory is not None:
            application.state.supabase_gateway = supabase_gateway_factory(settings)
        elif settings.supabase_configured:
            application.state.supabase_gateway = SupabaseGateway(
                settings.supabase_url or "",
                settings.supabase_publishable_key or "",
                settings.supabase_service_role_key or "",
            )
        yield

    application = FastAPI(
        title="Singapore Cosmetic Formulation Screening API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.frontend_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @application.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        regulatory_available = application.state.regulatory_store is not None
        identity_available = application.state.ingredient_catalog is not None
        return {
            "status": "ok" if regulatory_available and identity_available else "degraded",
            "regulatory_baseline": "available" if regulatory_available else "unavailable",
            "identity_catalogue": "available" if identity_available else "unavailable",
            "formulation_agent": "configured" if settings.configured else "not_configured",
            "agent_model": settings.agent_model,
            "explanation_model": settings.explanation_model,
            "persistence": "configured" if persistence_configured else "not_configured",
        }

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(_, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": _json_safe(error.errors())})

    application.include_router(cases_router)
    application.include_router(review_router)
    if persistence_configured:
        application.include_router(persistent_agent_router)
    else:
        # Keep the original scratch Agent available for local development and
        # deterministic tests. Production deployments configure Supabase and
        # use persistent case-scoped formulation routes instead.
        application.include_router(agent_router)
    application.include_router(screening_router)
    return application


app = create_app()
