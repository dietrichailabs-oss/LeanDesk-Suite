from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SuiteTheme:
    name: str
    mode: str
    description: str
    colors: dict[str, str]


def _palette(
    *, bg: str, panel: str, panel2: str, panel3: str, line: str, text: str,
    muted: str, cobalt: str, copper: str, jade: str, amber: str, orchid: str,
    coral: str, danger: str, field: str, field_text: str, selection: str,
    ribbon: str | None = None, workspace: str | None = None,
) -> dict[str, str]:
    def channel(value: str) -> tuple[int, int, int]:
        value = value.lstrip("#")
        return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))

    red, green, blue = channel(panel)
    is_light = 0.2126 * red + 0.7152 * green + 0.0722 * blue >= 150
    active_text = text if is_light else "#ffffff"
    return {
        "bg": bg, "panel": panel, "panel2": panel2, "panel3": panel3,
        "line": line, "text": text, "muted": muted, "cobalt": cobalt,
        "copper": copper, "jade": jade, "amber": amber, "orchid": orchid,
        "coral": coral, "danger": danger, "field": field,
        "field_text": field_text, "selection": selection,
        "ribbon": ribbon or panel, "workspace": workspace or bg,
        "button_bg": panel2, "button_hover": panel3, "button_pressed": selection,
        "button_text": text, "button_active_text": active_text,
        "accent_bg": cobalt, "accent_hover": selection if is_light else panel3,
        "accent_text": "#ffffff", "focus": cobalt, "border_subtle": line,
        "border_strong": cobalt if is_light else panel3, "active_indicator": copper,
        "status_bg": ribbon or panel, "scrollbar_track": panel,
        "scrollbar_thumb": panel3, "scrollbar_hover": selection,
        "scrollbar_pressed": cobalt, "tab_bg": bg, "tab_hover": panel2,
        "tab_selected_bg": cobalt, "tab_selected_text": "#ffffff",
        "menu_bg": panel, "menu_text": text, "menu_active_bg": selection,
        "menu_active_text": active_text, "disabled_text": muted,
        # Document/page colors deliberately remain neutral across suite themes.
        "paper": "#ffffff", "paper_alt": "#fdfcf8", "paper_text": "#202124",
        "grid": "#cfd5de", "header": "#eef1f5", "ruler": panel2,
        "ruler_text": muted,
    }


SUITE_THEMES: dict[str, SuiteTheme] = {
    "Dark": SuiteTheme("Dark", "dark", "Default deep navy workspace with clear blue accents.", _palette(bg="#111827", panel="#172033", panel2="#202b40", panel3="#263246", line="#31405a", text="#f4f1ea", muted="#aeb8ca", cobalt="#5f8dff", copper="#e18a4b", jade="#55d6b0", amber="#f3c35c", orchid="#c78af0", coral="#f07e89", danger="#f15b72", field="#101827", field_text="#f4f1ea", selection="#354b82", ribbon="#121a29", workspace="#263044")),
    "Light": SuiteTheme("Light", "light", "Default bright office theme with slate text and cobalt accents.", _palette(bg="#eef1f6", panel="#ffffff", panel2="#e7ebf2", panel3="#d9e0ea", line="#c2cad7", text="#1e293b", muted="#667085", cobalt="#356ae6", copper="#b85f2f", jade="#16866a", amber="#ad7500", orchid="#7d4bb3", coral="#bd4f62", danger="#c7374f", field="#ffffff", field_text="#1e293b", selection="#c9d9ff", ribbon="#f7f9fc", workspace="#d9dee7")),
    "Midnight Copper": SuiteTheme("Midnight Copper", "dark", "Premium charcoal and navy with warm copper details.", _palette(bg="#17181f", panel="#23252f", panel2="#2e3140", panel3="#3a3e50", line="#4a4e61", text="#f5f0e6", muted="#a9adba", cobalt="#4f7cff", copper="#d9874a", jade="#4ec9a5", amber="#f0b84b", orchid="#c178e8", coral="#ef7d7d", danger="#ef5d75", field="#181a24", field_text="#f5f0e6", selection="#3c568e", ribbon="#1c1e28", workspace="#31343e")),
    "Slate Blue": SuiteTheme("Slate Blue", "dark", "Cool professional slate with restrained blue highlights.", _palette(bg="#17212b", panel="#21303e", panel2="#2b3c4c", panel3="#354a5e", line="#486078", text="#edf4f8", muted="#a8bac8", cobalt="#68a5ff", copper="#cf8b5c", jade="#61c7aa", amber="#e2bd62", orchid="#a995db", coral="#e4828c", danger="#e66075", field="#15202a", field_text="#edf4f8", selection="#365f87", ribbon="#1b2834", workspace="#2d3945")),
    "Forest Slate": SuiteTheme("Forest Slate", "dark", "Deep evergreen panels with calm mint and brass accents.", _palette(bg="#14211d", panel="#1d302a", panel2="#294139", panel3="#345248", line="#45675b", text="#f0f4ec", muted="#abbcaf", cobalt="#6e9ed8", copper="#c98355", jade="#63c59e", amber="#d6b55c", orchid="#aa8bc5", coral="#dc7f79", danger="#dc5d67", field="#11201b", field_text="#f0f4ec", selection="#386b5b", ribbon="#192923", workspace="#2b3934")),
    "Burgundy Office": SuiteTheme("Burgundy Office", "dark", "Executive wine tones balanced by blue-gray controls.", _palette(bg="#24181d", panel="#342229", panel2="#463039", panel3="#583d48", line="#704f5b", text="#f7eeee", muted="#c2adb3", cobalt="#7797d6", copper="#d58b59", jade="#6fbaa0", amber="#dab962", orchid="#b58bc7", coral="#e2868d", danger="#e15f72", field="#21151a", field_text="#f7eeee", selection="#704052", ribbon="#2b1d23", workspace="#3a3034")),
    "Desert Sand": SuiteTheme("Desert Sand", "light", "Warm sand, espresso text, and understated terracotta accents.", _palette(bg="#eee7dc", panel="#fffaf2", panel2="#e5d8c7", panel3="#d7c6b0", line="#c3ad91", text="#372f29", muted="#756b62", cobalt="#416f9b", copper="#b7653d", jade="#3f856d", amber="#a77a20", orchid="#80649b", coral="#ae5c61", danger="#bb4253", field="#fffdf9", field_text="#372f29", selection="#dfcdb5", ribbon="#f6efe5", workspace="#d8d0c6")),
    "Ocean Mist": SuiteTheme("Ocean Mist", "light", "Airy blue-gray workspace with ocean teal accents.", _palette(bg="#e7eff2", panel="#f8fcfd", panel2="#d9e7eb", panel3="#c9dce2", line="#adc7cf", text="#17313c", muted="#607985", cobalt="#347fa5", copper="#b56c48", jade="#268f84", amber="#a78024", orchid="#6e68a6", coral="#b75f70", danger="#c7425b", field="#ffffff", field_text="#17313c", selection="#bfe2ee", ribbon="#eff6f8", workspace="#cedce1")),
    "Graphite Teal": SuiteTheme("Graphite Teal", "dark", "Neutral graphite with crisp teal navigation and focus states.", _palette(bg="#1a1e22", panel="#252b30", panel2="#30383e", panel3="#3b464d", line="#4d5b63", text="#f1f4f3", muted="#abb5b3", cobalt="#5d91bd", copper="#c57f55", jade="#4cc5b0", amber="#d6b85a", orchid="#a789c3", coral="#db7c82", danger="#df5c6e", field="#171b1e", field_text="#f1f4f3", selection="#356b68", ribbon="#20262a", workspace="#30363a")),
    "Lavender Office": SuiteTheme("Lavender Office", "light", "Soft lavender-gray workspace with restrained violet accents.", _palette(bg="#eeecf4", panel="#fbfaff", panel2="#e1deeb", panel3="#d2cde0", line="#bbb4cd", text="#302b3e", muted="#746e83", cobalt="#596fc1", copper="#b46b49", jade="#438778", amber="#9c7b22", orchid="#7b58b0", coral="#ad5a70", danger="#bd3f5b", field="#ffffff", field_text="#302b3e", selection="#d6cdf3", ribbon="#f4f2f9", workspace="#d8d5df")),
}


def get_theme(name: str) -> SuiteTheme:
    return SUITE_THEMES.get(name, SUITE_THEMES["Dark"])
