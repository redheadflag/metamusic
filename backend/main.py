import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.jobs import get_redis, close_redis
from api.upload import router as upload_router
from api.jobs import router as jobs_router
from api.media import router as media_router

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from soundcloud.api import SC_OAUTH_TOKEN

    if SC_OAUTH_TOKEN:
        logger.info("SoundCloud OAuth token loaded")
    else:
        logger.warning(
            "SC_OAUTH_TOKEN not set — SoundCloud fetch may fail for private/gated content."
        )
    await get_redis()
    logger.info("ARQ Redis pool ready")
    yield
    await close_redis()
    from services.sftp import close as close_sftp

    close_sftp()


app = FastAPI(title="metamusic", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")
app.include_router(media_router, prefix="/api")
