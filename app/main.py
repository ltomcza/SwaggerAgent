import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api import router
from app.mcp import router as mcp_router

# Ensure the logs directory exists before configuring FileHandler
_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_DIR / "swagger_agent.log"),
    ],
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan manager."""
    logger.info("Starting SwaggerAgent service...")
    yield
    logger.info("Shutting down SwaggerAgent service...")


app = FastAPI(
    title="SwaggerAgent API",
    description="AI agent that analyzes Swagger/OpenAPI pages. Extracts information about services and endpoints.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)
app.include_router(mcp_router)


@app.get("/health")
def health_check():
    """Health-check endpoint."""
    return {"status": "ok", "service": "SwaggerAgent"}
