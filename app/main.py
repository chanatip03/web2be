from fastapi import FastAPI
from app.api.v1 import api_router

app = FastAPI(title="WEB2 API")

app.include_router(api_router, prefix="/api/v1")

@app.get("/")
def health():
    return {"status": "ok"}
