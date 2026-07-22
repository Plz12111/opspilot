from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from opspilot.agent.graph import (
    DiagnosisSynthesizer,
    InvestigationRunner,
    RuleBasedDiagnosisSynthesizer,
)
from opspilot.api.routes import (
    alertmanager,
    evaluations,
    feishu,
    health,
    incidents,
    remediation,
    runbooks,
    workspace,
)
from opspilot.config import Settings, get_settings
from opspilot.db.models import Base
from opspilot.db.session import create_engine, create_session_factory
from opspilot.knowledge import HashEmbeddingProvider, HybridRunbookRetriever
from opspilot.remediation.executor import ActionExecutor, DemoActionExecutor
from opspilot.remediation.locks import ActionLockRegistry
from opspilot.services.investigation_coordinator import InvestigationCoordinator
from opspilot.tools.gateway import ToolGateway
from opspilot.tools.observability import create_observation_toolset
from opspilot.tools.runbooks import SearchRunbooksTool


def create_app(
    settings: Settings | None = None,
    tool_gateway: ToolGateway | None = None,
    diagnosis_synthesizer: DiagnosisSynthesizer | None = None,
    remediation_executor: ActionExecutor | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    engine = create_engine(resolved_settings.database_url)
    session_factory = create_session_factory(engine)
    embedding_provider = HashEmbeddingProvider()
    runbook_retriever = HybridRunbookRetriever(session_factory, embedding_provider)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        toolset = None
        if resolved_settings.db_auto_create:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        if app.state.tool_gateway is None:
            toolset = create_observation_toolset(resolved_settings)
            toolset.gateway.register(SearchRunbooksTool(runbook_retriever))
            app.state.tool_gateway = toolset.gateway
        await app.state.investigation_coordinator.recover()
        try:
            yield
        finally:
            await app.state.investigation_coordinator.close()
            if toolset is not None:
                await toolset.close()
            await engine.dispose()

    application = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.embedding_provider = embedding_provider
    application.state.runbook_retriever = runbook_retriever
    application.state.remediation_executor = remediation_executor or DemoActionExecutor()
    application.state.remediation_locks = ActionLockRegistry()
    application.state.remediation_approvers = {
        value.strip()
        for value in resolved_settings.remediation_approvers.split(",")
        if value.strip()
    }
    application.state.tool_gateway = tool_gateway
    application.state.diagnosis_synthesizer = (
        diagnosis_synthesizer or RuleBasedDiagnosisSynthesizer()
    )
    application.state.investigation_coordinator = InvestigationCoordinator(
        session_factory,
        lambda: InvestigationRunner(
            application.state.tool_gateway,
            application.state.diagnosis_synthesizer,
        ),
    )
    application.include_router(health.router)
    application.include_router(alertmanager.router)
    application.include_router(feishu.router)
    application.include_router(incidents.router)
    application.include_router(evaluations.router)
    application.include_router(runbooks.router)
    application.include_router(remediation.router)
    application.include_router(workspace.router)
    web_dir = Path(__file__).resolve().parent / "web"
    application.mount("/assets", StaticFiles(directory=web_dir), name="assets")

    @application.get("/", include_in_schema=False)
    async def dashboard() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    return application


app = create_app()
