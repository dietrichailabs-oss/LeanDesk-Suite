from leandesk.app import initial_window_bounds


def test_startup_window_preserves_full_desktop_visibility_at_1365_by_768() -> None:
    width, height, x, y = initial_window_bounds(1365, 768)

    assert (width, height, x, y) == (1325, 648, 20, 60)
    assert x >= 0 and y >= 0
    assert x + width <= 1365
    assert y + height <= 768


def test_startup_window_retains_designed_size_on_large_desktops() -> None:
    width, height, x, y = initial_window_bounds(1920, 1080)

    assert (width, height) == (1580, 940)
    assert (x, y) == (170, 70)
