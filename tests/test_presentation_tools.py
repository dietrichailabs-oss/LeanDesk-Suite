from dataclasses import dataclass

import pytest

from leandesk.presentation_tools import SlideshowSession, align, crop_image, distribute, group, rotate, ungroup, validate_slide_design


@dataclass
class Object:
    x: float
    y: float
    width: float = 20
    height: float = 10
    rotation: float = 0
    group_id: str | None = None
    crop: dict | None = None


@pytest.mark.parametrize("mode,field", [("left", "x"), ("right", "x"), ("center", "x"), ("top", "y"), ("bottom", "y"), ("middle", "y")])
def test_alignment_modes(mode, field):
    items = [Object(10, 20), Object(70, 90, 30, 40)]
    align(items, mode)
    if mode in {"left", "right", "top", "bottom"}:
        edge = [(item.x if mode == "left" else item.x + item.width) if field == "x" else (item.y if mode == "top" else item.y + item.height) for item in items]
        assert edge[0] == edge[1]
    else:
        centers = [(item.x + item.width / 2) if field == "x" else (item.y + item.height / 2) for item in items]
        assert centers[0] == centers[1]


@pytest.mark.parametrize("axis,field", [("horizontal", "x"), ("vertical", "y")])
def test_distribution_is_even(axis, field):
    items = [Object(0, 0), Object(95, 95), Object(30, 30), Object(60, 60)]
    distribute(items, axis)
    values = sorted(getattr(item, field) for item in items)
    assert values[1] - values[0] == pytest.approx(values[2] - values[1])
    assert values[2] - values[1] == pytest.approx(values[3] - values[2])


def test_group_rotate_ungroup_round_trip():
    items = [Object(0, 0), Object(20, 20)]
    identifier = group(items, "group-a")
    rotate(items, 450)
    assert identifier == "group-a"
    assert [item.rotation for item in items] == [90, 90]
    ungroup(items)
    assert all(item.group_id is None for item in items)


def test_crop_image_is_bounded_and_non_destructive_on_error():
    item = Object(0, 0)
    crop_image(item, .1, .2, .1, .2)
    previous = dict(item.crop)
    with pytest.raises(ValueError): crop_image(item, .6, 0, .5, 0)
    assert item.crop == previous


def test_slideshow_keyboard_navigation_and_escape():
    show = SlideshowSession(5)
    assert show.start() == 0
    assert show.handle_key("Right") == 1
    assert show.handle_key("End") == 4
    assert show.handle_key("Space") == 4
    assert show.handle_key("Home") == 0
    assert show.handle_key("Escape") is None
    assert show.running is False


def test_slideshow_start_from_current_and_bounds():
    show = SlideshowSession(100)
    assert show.start(67) == 67
    assert show.handle_key("PageUp") == 66
    with pytest.raises(ValueError): SlideshowSession(0).start()
    with pytest.raises(ValueError): SlideshowSession(1001)


@pytest.mark.parametrize("ratio", ["4:3", "16:9"])
@pytest.mark.parametrize("transition", ["none", "fade", "wipe"])
def test_common_slide_designs(ratio, transition):
    result = validate_slide_design(ratio, transition, "#FFFFFF")
    assert result["aspect_ratio"] == ratio
    assert result["transition"] == transition


def test_invalid_geometry_operations_fail_closed():
    with pytest.raises(ValueError): distribute([Object(0, 0), Object(1, 1)], "horizontal")
    with pytest.raises(ValueError): align([], "left")
    with pytest.raises(ValueError): rotate([Object(0, 0)], float("nan"))
    with pytest.raises(ValueError): validate_slide_design("21:9", "fade", "white")
