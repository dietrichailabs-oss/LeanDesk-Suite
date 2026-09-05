"""Shared bounded geometry and slideshow behavior for Slides and Draw."""

from __future__ import annotations

from dataclasses import dataclass
import math
import uuid
from typing import Any, Iterable


MAX_OBJECTS = 2_000


def _objects(items: Iterable[Any]) -> list[Any]:
    result = list(items)
    if not 1 <= len(result) <= MAX_OBJECTS:
        raise ValueError("Object selection is empty or exceeds supported bounds")
    for item in result:
        for field in ("x", "y", "width", "height"):
            if not hasattr(item, field):
                raise TypeError(f"Object lacks {field} geometry")
    return result


def align(items: Iterable[Any], mode: str) -> None:
    selected = _objects(items)
    mode = mode.lower()
    left = min(float(item.x) for item in selected)
    right = max(float(item.x) + float(item.width) for item in selected)
    top = min(float(item.y) for item in selected)
    bottom = max(float(item.y) + float(item.height) for item in selected)
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    for item in selected:
        if mode == "left": item.x = left
        elif mode == "center": item.x = center_x - float(item.width) / 2
        elif mode == "right": item.x = right - float(item.width)
        elif mode == "top": item.y = top
        elif mode == "middle": item.y = center_y - float(item.height) / 2
        elif mode == "bottom": item.y = bottom - float(item.height)
        else: raise ValueError("Unsupported alignment mode")


def distribute(items: Iterable[Any], axis: str) -> None:
    selected = _objects(items)
    if len(selected) < 3:
        raise ValueError("Distribution requires at least three objects")
    if axis.lower() == "horizontal":
        selected.sort(key=lambda item: float(item.x))
        start = float(selected[0].x)
        end = float(selected[-1].x)
        step = (end - start) / (len(selected) - 1)
        for index, item in enumerate(selected): item.x = start + step * index
    elif axis.lower() == "vertical":
        selected.sort(key=lambda item: float(item.y))
        start = float(selected[0].y)
        end = float(selected[-1].y)
        step = (end - start) / (len(selected) - 1)
        for index, item in enumerate(selected): item.y = start + step * index
    else:
        raise ValueError("Unsupported distribution axis")


def rotate(items: Iterable[Any], degrees: float) -> None:
    value = float(degrees)
    if not math.isfinite(value):
        raise ValueError("Rotation must be finite")
    for item in _objects(items):
        item.rotation = (float(getattr(item, "rotation", 0)) + value) % 360


def group(items: Iterable[Any], group_id: str | None = None) -> str:
    selected = _objects(items)
    if len(selected) < 2:
        raise ValueError("Grouping requires at least two objects")
    identifier = group_id or f"group-{uuid.uuid4().hex}"
    if len(identifier) > 100:
        raise ValueError("Group identifier is too long")
    for item in selected: item.group_id = identifier
    return identifier


def ungroup(items: Iterable[Any]) -> None:
    for item in _objects(items): item.group_id = None


def crop_image(item: Any, left: float, top: float, right: float, bottom: float) -> None:
    values = tuple(float(value) for value in (left, top, right, bottom))
    if any(not 0 <= value < 1 for value in values) or values[0] + values[2] >= 1 or values[1] + values[3] >= 1:
        raise ValueError("Crop values must leave a visible image area")
    item.crop = {"left": values[0], "top": values[1], "right": values[2], "bottom": values[3]}


@dataclass
class SlideshowSession:
    slide_count: int
    current_index: int = 0
    running: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.slide_count <= 1_000:
            raise ValueError("Slide count is outside supported bounds")
        if self.slide_count and not 0 <= self.current_index < self.slide_count:
            raise ValueError("Starting slide is outside the deck")

    def start(self, from_current: int | None = None) -> int:
        if not self.slide_count:
            raise ValueError("Cannot present an empty deck")
        if from_current is not None:
            if not 0 <= from_current < self.slide_count: raise ValueError("Starting slide is outside the deck")
            self.current_index = from_current
        self.running = True
        return self.current_index

    def handle_key(self, key: str) -> int | None:
        if not self.running:
            return None
        normalized = key.lower()
        if normalized in {"escape", "esc"}:
            self.running = False
            return None
        if normalized in {"right", "down", "space", "return", "pagedown"}:
            self.current_index = min(self.slide_count - 1, self.current_index + 1)
        elif normalized in {"left", "up", "backspace", "pageup"}:
            self.current_index = max(0, self.current_index - 1)
        elif normalized == "home": self.current_index = 0
        elif normalized == "end": self.current_index = self.slide_count - 1
        return self.current_index


def validate_slide_design(aspect_ratio: str, transition: str, background: str) -> dict[str, str]:
    if aspect_ratio not in {"4:3", "16:9"}:
        raise ValueError("Unsupported slide aspect ratio")
    if transition not in {"none", "fade", "wipe"}:
        raise ValueError("Unsupported slide transition")
    if not isinstance(background, str) or not background:
        raise ValueError("Slide background is required")
    return {"aspect_ratio": aspect_ratio, "transition": transition, "background": background}
