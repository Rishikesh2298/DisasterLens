import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dl.api.routers.benchmark import router as benchmark_router

app = FastAPI(
    title="DisasterLens Benchmark API",
    version="0.1.0",
    description="Benchmark results for synthetic scenes; not an emergency system.",
)
origins = [
    value.strip()
    for value in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if value.strip()
]
app.add_middleware(
    CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"]
)
app.include_router(benchmark_router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "benchmark", "synthetic_only": True}
