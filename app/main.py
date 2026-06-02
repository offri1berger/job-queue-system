from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import create_tables
from app.redis_client import connect, disconnect


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    await connect()
    yield
    await disconnect()


app = FastAPI(lifespan=lifespan)

# from app.api.routes.jobs import router as jobs_router
# app.include_router(jobs_router, prefix="/jobs")


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
