"""
Database models package.
Import all models here so Alembic can discover them for autogenerate.
"""
from shared.database.models.movie import (
    Movie,
    Genre,
    Person,
    Studio,
    Collection,
    MovieGenre,
    MoviePerson,
    MovieStudio,
)
from shared.database.models.tvshow import TvShow, Season, Episode
from shared.database.models.download import Download
from shared.database.models.workflow import WorkflowJob, WorkflowStep, PlatformEvent
from shared.database.models.quality import MediaQuality, QualityRule
from shared.database.models.subtitle import Subtitle
from shared.database.models.duplicate import Duplicate
from shared.database.models.health import HealthReport, HealthIssue
from shared.database.models.storage import StorageReport
from shared.database.models.entertainment import IptvChannel, RadioStation, Recording, EpgProgram

__all__ = [
    "Movie", "Genre", "Person", "Studio", "Collection",
    "MovieGenre", "MoviePerson", "MovieStudio",
    "TvShow", "Season", "Episode",
    "Download",
    "WorkflowJob", "WorkflowStep", "PlatformEvent",
    "MediaQuality", "QualityRule",
    "Subtitle",
    "Duplicate",
    "HealthReport", "HealthIssue",
    "StorageReport",
    "IptvChannel", "RadioStation", "Recording", "EpgProgram",
]
