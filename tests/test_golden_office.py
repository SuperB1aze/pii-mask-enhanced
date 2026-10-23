"""Golden set для файлов Office: эталоны сделаны настоящими Word, Excel и PowerPoint.

Самодельные фикстуры содержат только то, что в них положили. Файл из настоящего Office
несет и то, о чем никто не думал: миниатюру слайда, путь сохранения, автора сводной
таблицы. Здесь оригинал ищется во всех частях архива, включая вложенные книги
диаграмм, и в двух кодировках. Как пересобрать эталоны - tests/golden/office/build.py.
"""
import io
import zipfile
from pathlib import Path

import pytest

from pii_mask_enhanced.engine.core import Masker
from pii_mask_enhanced.formats import excel, powerpoint, word

OFFICE = Path(__file__).parent / "golden" / "office"

# автор и путь сохранения в эталонах вымышленные (build.py)
ORIGINALS = ["Соколов", "Воронцов", "Ромашка", "sokolova@example.ru", "vorontsov@example.ru",
             "Лебедева", "lebedeva"]

FORMATS = [
    ("report.docx", word.mask_document, word.unmask_document),
    ("staff.xlsx", excel.mask_workbook, excel.unmask_workbook),
    ("deck.pptx", powerpoint.mask_presentation, powerpoint.unmask_presentation),
]


def _scan(blob: bytes, where: str, found: list[str]) -> list[str]:
    """Оригиналы в любой части архива, включая вложенные архивы, в UTF-8 и UTF-16."""
    if blob[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for name in z.namelist():
                _scan(z.read(name), f"{where}/{name}", found)
        return found
    found += [f"{where}: {o}" for o in ORIGINALS
              if o.encode("utf-8") in blob or o.encode("utf-16-le") in blob]
    return found


def _leaks(path: Path) -> list[str]:
    return _scan(path.read_bytes(), path.name, [])


@pytest.mark.parametrize("name, mask, unmask", FORMATS)
def test_office_golden_has_no_leaks(tmp_path, name, mask, unmask):
    src = OFFICE / name
    assert _leaks(src), "в эталоне должны быть оригиналы - иначе проверять нечего"
    masked = tmp_path / f"masked{src.suffix}"
    mapping = mask(src, masked, Masker(types=("PERSON", "EMAIL", "ORG")))
    assert not _leaks(masked), f"утекло: {_leaks(masked)}"
    with zipfile.ZipFile(masked) as z:
        assert not [n for n in z.namelist() if "thumbnail" in n], "миниатюра - картинка с оригиналом"

    restored = tmp_path / f"restored{src.suffix}"
    unmask(masked, restored, mapping)
    assert any("sokolova@example.ru" in hit for hit in _leaks(restored)), "оригиналы не вернулись"
