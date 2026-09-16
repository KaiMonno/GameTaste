from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Game(Base):
    """Unified, enriched game record. IGDB is the source of truth for id/core
    metadata; HLTB and LLM enrichment fill in the fields IGDB doesn't have.
    Populated by scheduled sync/enrichment scripts, never written per-request.
    """

    __tablename__ = "games"

    # IGDB's own id is the primary key - avoids a separate mapping table.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)

    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    genres: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    platforms: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    game_modes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)

    # IGDB's own category enum (0 = main_game, 1 = dlc_addon, 2 = expansion, ...).
    # Null for rows synced before this field existed. Used to exclude DLC/
    # expansions from recommendations by default - see services/scoring.py.
    igdb_category: Mapped[int | None] = mapped_column(Integer, nullable=True)

    igdb_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    igdb_rating_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    similar_game_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)

    hltb_main: Mapped[float | None] = mapped_column(Float, nullable=True)
    hltb_main_extra: Mapped[float | None] = mapped_column(Float, nullable=True)
    hltb_completionist: Mapped[float | None] = mapped_column(Float, nullable=True)

    # LLM-enriched (phase 2) - null until the enrichment job has run on this game.
    # (difficulty was considered but deliberately excluded - no ground truth
    # source exists and it was cut from scope, see mvp-plan.md section 1.)
    story_gameplay_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_warnings: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)

    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enrichment_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # embedding (pgvector) is a v2 addition once similarity search is needed -
    # see game-recommender-architecture.md section 6. Add via a new migration
    # rather than guessing the column shape now.
