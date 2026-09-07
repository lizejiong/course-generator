from fastapi import FastAPI

from app.api.router import build_router
from app.config import Settings, get_settings
from app.db.session import create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.prepare_paths()
    app = FastAPI(title="课程生成器 API", version="0.1.0")
    app.include_router(build_router(settings, create_session_factory(settings)))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
