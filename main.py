from dotenv import load_dotenv
from fastapi import FastAPI

from app.api.browse import router as browse_router
from app.api.ingest import router as ingest_router
from app.database import Base, engine
import app.models  # noqa: F401

load_dotenv()

app = FastAPI(title="CT Doc Trace API")
Base.metadata.create_all(bind=engine)
app.include_router(ingest_router)
app.include_router(browse_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
