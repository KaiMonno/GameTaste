from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import games, recommendations

app = FastAPI(title="GameTaste API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recommendations.router)
app.include_router(games.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
