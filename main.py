import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import db
from config import settings
from scheduler import start_scheduler, shutdown_scheduler
from classifier import classify_feed_entries

# Import routers
from routers.feeds import router as feeds_router
from routers.categories import router as categories_router
from routers.entries import router as entries_router
from routers.profile import router as profile_router
from routers.settings import router as settings_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("myrss")

# FastAPI lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB schema
    db.init_db()
    
    # Start the background scheduler
    start_scheduler()
    
    yield
    
    # Shutdown the background scheduler
    shutdown_scheduler()

app = FastAPI(
    title="KickRSS API Backend",
    description="Backend for AI RSS Reader (Modularized)",
    version="1.1.0",
    lifespan=lifespan
)

# CORS configuration: Allow frontend to run independently on different hosts/ports
# By default, allow all, but keep configurable if needed in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount APIRouter instances
app.include_router(feeds_router, tags=["feeds"])
app.include_router(categories_router, tags=["categories"])
app.include_router(entries_router, tags=["entries"])
app.include_router(profile_router, tags=["profile"])
app.include_router(settings_router, tags=["settings"])

@app.get("/healthz", tags=["health"])
def healthz():
    return {"ok": True}

# Serve frontend static files if the static directory exists (making it optional for pure API setups)
STATIC_DIR = "static"
if os.path.exists(STATIC_DIR):
    logger.info(f"Mounting static files directory: {STATIC_DIR}")
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
else:
    logger.warning(f"Static directory '{STATIC_DIR}' not found. Serving as pure API backend.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
