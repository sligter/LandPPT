"""Shared rules for projects planned as illustrated video scenes."""

import re
from html.parser import HTMLParser
from typing import Any, Literal, Mapping, Sequence

ContentMode = Literal["presentation", "video_explainer"]
VIDEO_EXPLAINER = "video_explainer"
VIDEO_SCENE_TYPES = {"content", "conclusion"}


def is_video_explainer(requirements: Mapping[str, Any] | None) -> bool:
    return bool(requirements and requirements.get("content_mode") == VIDEO_EXPLAINER)


class _CueLabels(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.labels: dict[int, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = dict(attrs)
        step, label = fields.get("data-video-step"), fields.get("data-video-cue")
        if step is not None and step in {"1", "2", "3", "4"}:
            step_number = int(step)
            if label and label.strip():
                self.labels[step_number] = self.labels.get(step_number) or label.strip()[:80]
            else:
                self.labels.setdefault(step_number, "")


def _video_steps(html: str) -> dict[int, str]:
    parser = _CueLabels()
    parser.feed(html)
    return dict(sorted(parser.labels.items()))


def video_cue_labels(html: str) -> list[str]:
    return [label for label in _video_steps(html).values() if label]


def _cue_text(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.casefold())


def build_reveal_schedule(
    html: str, cues: Sequence[tuple[int, str]], duration_ms: int
) -> dict[int, int]:
    """Match steps to spoken cue starts, with evenly spaced timing when a cue is missing."""
    steps = _video_steps(html)
    if not steps or duration_ms <= 0:
        return {}
    spoken_cues = tuple(sorted((start, _cue_text(text)) for start, text in cues))
    spacing = min(350, duration_ms // (len(steps) + 1))
    schedule: dict[int, int] = {}
    earliest = 0
    for index, (step, label) in enumerate(steps.items()):
        phrase = _cue_text(label)
        latest = duration_ms - (len(steps) - index) * spacing
        fallback = duration_ms * index // len(steps)
        matched = next(
            (start for start, text in spoken_cues if earliest <= start <= latest and phrase and phrase in text),
            fallback,
        )
        schedule[step] = min(max(matched, earliest), latest)
        earliest = schedule[step] + spacing
    return schedule
