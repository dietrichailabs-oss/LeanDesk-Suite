"""Presenter must display the editor's objects, not only title and body."""
import base64
import io
from types import SimpleNamespace

import pytest

from leandesk import slides


class CanvasProbe:
    def __init__(self, *args, **kwargs):
        self.items = []
        self.bindings = {}

    def delete(self, _tag):
        self.items.clear()

    def winfo_width(self):
        return 1200

    def winfo_height(self):
        return 720

    def pack(self, **kwargs):
        pass

    def bind(self, name, callback):
        self.bindings[name] = callback

    def create_rectangle(self, *args, **kwargs):
        self.items.append(("rectangle", args, kwargs))

    def create_text(self, *args, **kwargs):
        self.items.append(("text", args, kwargs))

    def create_oval(self, *args, **kwargs):
        self.items.append(("oval", args, kwargs))

    def create_image(self, *args, **kwargs):
        self.items.append(("image", args, kwargs))


class WindowProbe:
    def __init__(self):
        self.bindings = {}
        self.destroyed = False

    def title(self, _value):
        pass

    def configure(self, **kwargs):
        pass

    def geometry(self, _value):
        pass

    def bind(self, name, callback):
        self.bindings[name] = callback

    def after(self, _delay, callback):
        callback()

    def destroy(self):
        self.destroyed = True


def present(monkeypatch, models):
    window, canvas = WindowProbe(), CanvasProbe()
    monkeypatch.setattr(slides.tk, "Toplevel", lambda _parent: window)
    monkeypatch.setattr(slides.tk, "Canvas", lambda *args, **kwargs: canvas)
    frame = SimpleNamespace(
        deck=slides.DeckModel(slides=models), current_index=lambda: 0,
        _render_slide_content=slides.SlidesFrame._render_slide_content,
    )
    slides.SlidesFrame.present(frame)
    return window, canvas


@pytest.mark.parametrize("theme", tuple(slides.THEMES))
@pytest.mark.parametrize("kind", ("table", "chart", "text", "shape"))
def test_presenter_matches_editor_objects(monkeypatch, theme, kind):
    item = slides.SlideObject(kind=kind, text="object marker", data={
        "rows": 2, "cols": 2, "values": [["cell marker", "b"], ["c", "d"]]
        if kind == "table" else [3, 5, 2],
    })
    model = slides.SlideModel(title="heading", body="body", theme=theme, objects=[item])
    editor = CanvasProbe()
    slides.SlidesFrame._render_slide_content(editor, model)
    _, presenter = present(monkeypatch, [model])
    assert presenter.items[:-1] == editor.items
    assert presenter.items[-1][2]["text"] == "1 / 1"
    if kind == "table":
        assert any(row[2].get("text") == "cell marker" for row in presenter.items)
        assert sum(row[0] == "rectangle" for row in presenter.items) == 6
    elif kind == "chart":
        assert sum(row[0] == "rectangle" for row in presenter.items) == 5
    else:
        assert any(row[2].get("text") == "object marker" for row in presenter.items)


def test_presenter_navigation_redraws_objects_and_exits(monkeypatch):
    models = [slides.SlideModel(objects=[slides.SlideObject(kind="text", text=value)])
              for value in ("first object", "second object")]
    window, canvas = present(monkeypatch, models)
    window.bindings["<Right>"](None)
    assert any(row[2].get("text") == "second object" for row in canvas.items)
    assert not any(row[2].get("text") == "first object" for row in canvas.items)
    assert canvas.items[-1][2]["text"] == "2 / 2"
    window.bindings["<space>"](None)
    assert canvas.items[-1][2]["text"] == "2 / 2"
    window.bindings["<Left>"](None)
    assert any(row[2].get("text") == "first object" for row in canvas.items)
    window.bindings["<Escape>"](None)
    assert window.destroyed


def test_presenter_keeps_its_own_embedded_image_reference(monkeypatch):
    from PIL import Image, ImageTk
    stream = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(stream, format="PNG")
    model = slides.SlideModel(image_data=base64.b64encode(stream.getvalue()).decode("ascii"),
                              image_media_type="image/png")
    monkeypatch.setattr(ImageTk, "PhotoImage", lambda image, master: SimpleNamespace(master=master))
    editor = CanvasProbe()
    slides.SlidesFrame._render_slide_content(editor, model)
    editor_ref = editor._leandesk_image_ref
    _, presenter = present(monkeypatch, [model])
    assert presenter._leandesk_image_ref.master is presenter
    assert editor._leandesk_image_ref is editor_ref
    assert editor_ref.master is editor
    assert any(row[0] == "image" for row in presenter.items)


def test_selection_highlight_is_editor_only(monkeypatch):
    item = slides.SlideObject(kind="table", data={"rows": 1, "cols": 1, "values": [["cell"]]})
    model = slides.SlideModel(objects=[item])
    editor = CanvasProbe()
    slides.SlidesFrame._render_slide_content(editor, model, selected_object_id=item.object_id)
    _, presenter = present(monkeypatch, [model])
    assert editor.items[4][2]["outline"] == slides.THEMES[model.theme]["accent"]
    assert presenter.items[4][2]["outline"] == item.stroke
