"""Provider-agnostic scene model and same-track pair selection."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass
class Scene:
    provider: str
    collection: str
    scene_id: str
    datetime: datetime
    relative_orbit: Optional[int] = None
    orbit_state: Optional[str] = None
    cloud_cover: Optional[float] = None
    assets: dict = field(default_factory=dict)  # band name -> href (or provider-specific handle)
    props: dict = field(default_factory=dict)   # extra metadata (e.g. S2 processing baseline)

    @property
    def track_key(self):
        """Scenes with equal track_key share viewing geometry and can be compared pixel by pixel.
        Falls back to acquisition time-of-day when the provider gives no orbit metadata."""
        if self.relative_orbit is not None:
            return (self.relative_orbit, self.orbit_state)
        return ("tod", round(self.datetime.hour + self.datetime.minute / 60))


@dataclass
class ScenePair:
    pre: Scene
    post: Scene

    @property
    def gap_days(self) -> float:
        return (self.post.datetime - self.pre.datetime).total_seconds() / 86400

    def describe(self) -> str:
        return (f"{self.pre.datetime:%Y-%m-%d %H:%M} -> {self.post.datetime:%Y-%m-%d %H:%M} UTC "
                f"track={self.post.track_key} gap={self.gap_days:.0f}d ({self.post.provider})")


def as_utc(d) -> datetime:
    if isinstance(d, str):
        d = datetime.fromisoformat(d.replace("Z", "+00:00"))
    return d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc)


def select_pairs(scenes: list[Scene], event: datetime, max_post_days=12) -> list[ScenePair]:
    """For every track, pair the first post-event scene with the latest pre-event scene of the
    same track. Ranked by how soon after the event the post image is (rescuers need the
    earliest look), then by the shortest pre/post gap (less unrelated change)."""
    event = as_utc(event)
    by_track: dict = {}
    for s in scenes:
        by_track.setdefault(s.track_key, []).append(s)
    pairs = []
    for group in by_track.values():
        pre = [s for s in group if s.datetime < event]
        post = [s for s in group if event <= s.datetime <= event + timedelta(days=max_post_days)]
        if pre and post:
            pairs.append(ScenePair(max(pre, key=lambda s: s.datetime), min(post, key=lambda s: s.datetime)))
    return sorted(pairs, key=lambda p: (p.post.datetime, p.gap_days))
