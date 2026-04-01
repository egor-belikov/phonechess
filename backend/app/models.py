"""
Database models for users, games and private invites.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    login_name: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True, index=True)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    blitz_rating: Mapped[int] = mapped_column(Integer, default=1500, nullable=False)
    rapid_rating: Mapped[int] = mapped_column(Integer, default=1500, nullable=False)
    games_played: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    has_started_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow)


class GameRecord(Base):
    __tablename__ = "games"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    time_control_key: Mapped[str] = mapped_column(String(16), nullable=False)
    white_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    black_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    white_username: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    black_username: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    fen: Mapped[str] = mapped_column(Text, nullable=False)
    white_remaining_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    black_remaining_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    result_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    moves: Mapped[list["GameMoveRecord"]] = relationship(back_populates="game", cascade="all, delete-orphan")


class GameMoveRecord(Base):
    __tablename__ = "game_moves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True)
    ply: Mapped[int] = mapped_column(Integer, nullable=False)
    san: Mapped[str] = mapped_column(String(64), nullable=False)
    uci_from: Mapped[str] = mapped_column(String(2), nullable=False)
    uci_to: Mapped[str] = mapped_column(String(2), nullable=False)
    promotion: Mapped[str | None] = mapped_column(String(1), nullable=True)
    move_time_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fen_after: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow)

    game: Mapped["GameRecord"] = relationship(back_populates="moves")


class PrivateInviteRecord(Base):
    __tablename__ = "private_invites"

    invite_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    creator_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    invited_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    time_control_key: Mapped[str] = mapped_column(String(16), nullable=False)
    game_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TournamentRecord(Base):
    __tablename__ = "tournaments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    format: Mapped[str] = mapped_column(String(16), nullable=False)  # swiss | ko
    time_control_key: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # active | finished
    min_players: Mapped[int] = mapped_column(Integer, nullable=False)
    swiss_rounds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class TournamentParticipantRecord(Base):
    __tablename__ = "tournament_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tournament_id: Mapped[str] = mapped_column(String(64), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    place: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    buchholz: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reward_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TournamentMatchRecord(Base):
    __tablename__ = "tournament_matches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tournament_id: Mapped[str] = mapped_column(String(64), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    round_index: Mapped[int] = mapped_column(Integer, nullable=False)
    white_id: Mapped[str] = mapped_column(String(64), nullable=False)
    black_id: Mapped[str] = mapped_column(String(64), nullable=False)
    game_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[str | None] = mapped_column(String(8), nullable=True)  # 1-0 | 0-1 | 1/2-1/2
    stage: Mapped[str] = mapped_column(String(24), default="swiss", nullable=False)  # swiss | ko | bronze

