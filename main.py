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

import hmac
import hashlib
import time
from pydantic import BaseModel
from fastapi import Request, Response
from fastapi.responses import JSONResponse

# Session Token Helpers
def get_signing_key(password: str) -> bytes:
    return hashlib.sha256(password.encode('utf-8')).digest()

def generate_session_token(password: str) -> str:
    payload = str(int(time.time()))
    key = get_signing_key(password)
    sig = hmac.new(key, payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"

def verify_session_token(token: str, password: str) -> bool:
    try:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return False
        payload, sig = parts
        key = get_signing_key(password)
        expected_sig = hmac.new(key, payload.encode('utf-8'), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return False
        timestamp = int(payload)
        if time.time() - timestamp > 7776000:  # 90 days
            return False
        return True
    except Exception:
        return False

from collections import defaultdict

# In-memory login attempt rate limiter: ip -> {"count": int, "blocked_until": float}
login_attempts = defaultdict(lambda: {"count": 0, "blocked_until": 0.0})

def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "127.0.0.1"

class LoginRequest(BaseModel):
    password: str

# Mount APIRouter instances
app.include_router(feeds_router, tags=["feeds"])
app.include_router(categories_router, tags=["categories"])
app.include_router(entries_router, tags=["entries"])
app.include_router(profile_router, tags=["profile"])
app.include_router(settings_router, tags=["settings"])

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not settings.access_password:
        return await call_next(request)
        
    path = request.url.path
    protected_prefixes = [
        "/feeds", "/categories", "/entries", "/profile", "/settings", "/refresh", "/maintenance"
    ]
    
    is_protected = False
    for prefix in protected_prefixes:
        if path == prefix or path.startswith(prefix + "/"):
            is_protected = True
            break
            
    if is_protected:
        session_token = request.cookies.get("kickrss_session")
        if not session_token or not verify_session_token(session_token, settings.access_password):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"}
            )
            
    return await call_next(request)

@app.post("/login", tags=["auth"])
def login(request: Request, data: LoginRequest, response: Response):
    if not settings.access_password:
        return {"ok": True, "message": "Auth not enabled"}
        
    client_ip = get_client_ip(request)
    now = time.time()
    
    # Check if IP is currently blocked
    record = login_attempts[client_ip]
    if record["blocked_until"] > now:
        remaining = int(record["blocked_until"] - now)
        logger.warning(f"Blocked login attempt from IP {client_ip}. Remaining block time: {remaining}s")
        return JSONResponse(
            status_code=429,
            content={"detail": f"Too many failed attempts. Try again in {remaining} seconds."}
        )
        
    if data.password == settings.access_password:
        # Success: reset rate limit record
        if client_ip in login_attempts:
            del login_attempts[client_ip]
            
        token = generate_session_token(settings.access_password)
        response.set_cookie(
            key="kickrss_session",
            value=token,
            max_age=7776000,  # 90 days
            httponly=True,
            path="/",
            samesite="lax",
            secure=False
        )
        return {"ok": True}
        
    # Failed attempt: log, sleep, and record
    logger.warning(f"Failed login attempt from IP: {client_ip}")
    time.sleep(1.0) # Slow down brute force
    
    record["count"] += 1
    if record["count"] >= 5:
        record["blocked_until"] = now + 900 # 15 minutes lockout
        record["count"] = 0
        logger.warning(f"IP {client_ip} has been locked out for 15 minutes due to 5 failed login attempts.")
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many failed attempts. locked out for 15 minutes."}
        )
        
    remaining_attempts = 5 - record["count"]
    return JSONResponse(
        status_code=401,
        content={"detail": f"Incorrect password. {remaining_attempts} attempts remaining."}
    )

@app.post("/logout", tags=["auth"])
def logout(response: Response):
    response.delete_cookie(key="kickrss_session", path="/")
    return {"ok": True}

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
