from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .core import PERSONAL_DICTIONARY_FILE, atomic_write_json, read_json

WORD_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")

# Fallback vocabulary keeps development/source runs usable when the optional
# dictionary package is not installed. Windows release builds include
# pyspellchecker and its substantially larger offline English frequency list.
FALLBACK_WORDS = set(
    """
    a able about above accept account across action active add after again against age ago agree all allow almost alone along already also always am among amount an and another answer any anyone anything app application are area around as ask at available away back backup base be because become been before begin below best better between big both build business but by call can cannot case change check clean close cloud code color come common complete computer contact content continue control copy could create current custom data date day default delete design desktop detail did different do document does done down draw during each easy edit editor else email end enough enter error even every example export fast feature few file fill find first folder follow for form format free from full future get give go good got great group had has have he help her here high history home how however i icon idea if image import in include includes information input install installer into is it item its keep know known language large last later launch layout lean learn left less let like line link list live local look made make many may me menu message might model module more most move much must my name need new next no normal not note now number of off office old on once one only open option or order other our out over own page paragraph part people place plan please point possible power preview print private program project public put quick ready real recent record release remove replace report reset restore result review right run safe save search see select send set settings should show simple since small so software some source space spell start status still store style suite support sure system tab table take task text than that the their them then there these they thing this those through time to today tool top track try two type under undo update use used useful user value version view want was way we web well were what when where which while who why will window with word work would write writer year yes you your
    headings sheets slides notes tasks calendar contacts review insert layout clipboard font paragraph styles editing spacing spellcheck dictionary extensive offline correction suggestion personal ignore ruler zoom page numbers headers footers tables images links workflow professional clarity productivity experience powerful formatting focus designed control communicate impact beautiful
    """.split()
)


@dataclass(frozen=True)
class Misspelling:
    word: str
    start: int
    end: int


class SpellService:
    """Offline English spell checking with personal dictionary support."""

    def __init__(self, personal_path: Path = PERSONAL_DICTIONARY_FILE) -> None:
        self.personal_path = personal_path
        self.fallback_words = set(FALLBACK_WORDS)
        candidates = [
            Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "assets" / "english_words.txt",
            Path(__file__).resolve().parent.parent / "assets" / "english_words.txt",
        ]
        for dictionary_path in candidates:
            if dictionary_path.is_file():
                try:
                    self.fallback_words.update(
                        line.strip().lower()
                        for line in dictionary_path.read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    )
                    break
                except OSError:
                    pass
        self.personal_words = {
            str(word).strip().lower()
            for word in read_json(personal_path, [])
            if str(word).strip()
        }
        self.engine = None
        self.engine_name = "Built-in fallback dictionary"
        try:
            from spellchecker import SpellChecker

            self.engine = SpellChecker(language="en", distance=2)
            if self.personal_words:
                self.engine.word_frequency.load_words(self.personal_words)
            self.engine_name = "PySpellChecker offline English dictionary"
        except Exception:
            self.engine = None

    @property
    def dictionary_size(self) -> int:
        if self.engine is not None:
            try:
                return len(self.engine.word_frequency.dictionary)
            except Exception:
                return 0
        return len(self.fallback_words) + len(self.personal_words)

    @staticmethod
    def normalize(word: str) -> str:
        return word.strip("'’- ").lower()

    def should_ignore(self, word: str) -> bool:
        value = self.normalize(word)
        if len(value) < 2:
            return True
        if value in self.personal_words:
            return True
        if any(char.isdigit() for char in value):
            return True
        if word.isupper() and len(word) > 1:
            return True
        if re.match(r"^(https?|www)\b", value):
            return True
        return False

    def is_correct(self, word: str) -> bool:
        value = self.normalize(word)
        if self.should_ignore(word):
            return True
        if self.engine is not None:
            return value not in self.engine.unknown([value])
        if value in self.fallback_words:
            return True
        # Basic morphology makes the fallback less noisy.
        for suffix in ("s", "es", "ed", "ing", "ly", "er", "ers", "est", "ment", "tion", "ions"):
            if value.endswith(suffix) and value[: -len(suffix)] in self.fallback_words:
                return True
        return False

    def misspellings(self, text: str) -> list[Misspelling]:
        rows: list[Misspelling] = []
        for match in WORD_RE.finditer(text):
            word = match.group(0)
            if not self.is_correct(word):
                rows.append(Misspelling(word, match.start(), match.end()))
        return rows

    def suggestions(self, word: str, limit: int = 8) -> list[str]:
        value = self.normalize(word)
        if not value:
            return []
        if self.engine is not None:
            candidates = self.engine.candidates(value) or set()
            ranked = sorted(
                {str(item) for item in candidates if item},
                key=lambda item: (self._distance(value, item), len(item), item),
            )
            return ranked[:limit]
        pool = [
            item for item in self.fallback_words
            if item[:1] == value[:1] and abs(len(item) - len(value)) <= 2
        ]
        ranked = sorted(
            pool,
            key=lambda item: (self._distance(value, item), abs(len(value) - len(item)), item),
        )
        return [item for item in ranked if self._distance(value, item) <= 2][:limit]

    def add_personal(self, word: str) -> None:
        value = self.normalize(word)
        if not value:
            return
        self.personal_words.add(value)
        if self.engine is not None:
            self.engine.word_frequency.load_words([value])
        atomic_write_json(self.personal_path, sorted(self.personal_words))

    def remove_personal(self, word: str) -> None:
        value = self.normalize(word)
        self.personal_words.discard(value)
        atomic_write_json(self.personal_path, sorted(self.personal_words))

    @staticmethod
    def _distance(left: str, right: str) -> int:
        if left == right:
            return 0
        if not left:
            return len(right)
        if not right:
            return len(left)
        previous = list(range(len(right) + 1))
        for i, lchar in enumerate(left, 1):
            current = [i]
            for j, rchar in enumerate(right, 1):
                current.append(
                    min(
                        current[-1] + 1,
                        previous[j] + 1,
                        previous[j - 1] + (lchar != rchar),
                    )
                )
            previous = current
        return previous[-1]


def unique_misspelled_words(text: str, service: SpellService) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for row in service.misspellings(text):
        value = row.word.lower()
        if value not in seen:
            seen.add(value)
            result.append(row.word)
    return result
