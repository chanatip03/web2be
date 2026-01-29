from fastapi import FastAPI
from app import api_router
from app.core.security_scan import security_router

app = FastAPI(title="WEB2 API")

app.include_router(api_router, prefix="/api/")
app.include_router(security_router, prefix="/security")

@app.get("/")
def health():
    return {"status": "ok"}
