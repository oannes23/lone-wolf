"""Pydantic schemas for leaderboard endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class BookInfo(BaseModel):
    """Minimal book info embedded in leaderboard responses."""

    id: int
    title: str


class LeaderboardEntry(BaseModel):
    """A single ranked entry on a leaderboard list."""

    username: str
    death_count: int
    decisions: int


class EnduranceEntry(BaseModel):
    """Leaderboard entry showing highest endurance at victory."""

    username: str
    endurance: int
    death_count: int


class DeathSceneEntry(BaseModel):
    """A scene ranked by how often characters die there."""

    scene_number: int
    death_count: int


class DisciplinePopularityEntry(BaseModel):
    """Discipline pick-rate entry for a leaderboard."""

    discipline: str
    pick_rate: float


class ItemUsageEntry(BaseModel):
    """Item pickup-rate entry for a leaderboard."""

    item_name: str
    pickup_rate: float


class BookLeaderboard(BaseModel):
    """Per-book leaderboard response."""

    book: BookInfo
    completions: int
    fewest_deaths: list[LeaderboardEntry]
    fewest_decisions: list[LeaderboardEntry]
    highest_endurance_at_victory: list[EnduranceEntry]
    most_common_death_scenes: list[DeathSceneEntry]
    discipline_popularity: list[DisciplinePopularityEntry]
    item_usage: list[ItemUsageEntry]


class OverallLeaderboard(BaseModel):
    """Aggregate leaderboard across all books."""

    total_completions: int
    total_characters: int
    highest_endurance_at_victory: list[EnduranceEntry]
    most_completions: list[LeaderboardEntry]
