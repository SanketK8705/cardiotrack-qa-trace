from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

app = FastAPI(title="CT Doc Trace API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
