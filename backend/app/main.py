from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import games, recommendations

app = FastAPI(title="GameTaste API")

app.add_middleware(
    CORSMiddleware,
    # allow_origin_regex, not a fixed port, because `next dev` silently binds
    # the next free port (3001, 3002, ...) whenever 3000 is already taken by
    # another process - a hardcoded "localhost:3000" then fails every
    # frontend fetch with a browser-side CORS error that looks identical to
    # the backend being down, with no server-side log to point at why.
    allow_origin_regex=r"http://localhost:\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recommendations.router)
app.include_router(games.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
