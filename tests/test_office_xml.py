"""Общие части .docx и .xlsx."""
import re
import zipfile

import pytest

from pii_mask_enhanced.formats import office_xml

_NO_TEXT = re.compile(r"^(\[Content_Types\]\.xml|_rels/)")


def test_empty_node_with_attributes_does_not_swallow_next():
    """<t xml:space="preserve"/> пустой - следующий узел читается сам по себе."""
    body = '<r><t xml:space="preserve"/></r><r><t>Иванов</t></r>'.encode()
    assert office_xml.runs_text(body) == "Иванов"


def _unknown(tmp_path, parts: dict[str, bytes | str]) -> list[str]:
    path = tmp_path / "f.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        for name, blob in parts.items():
            z.writestr(name, blob)
    with zipfile.ZipFile(path) as z:
        return office_xml.unknown_text_parts(z, set(), _NO_TEXT)


def test_chart_cache_without_t_refuses(tmp_path):
    """Подписи диаграммы - копия ячеек в <c:v>: ячейку замаскируем, а копия уйдет как есть."""
    chart = ('<?xml version="1.0"?><c:chartSpace xmlns:c="c"><c:strCache><c:pt idx="0">'
             '<c:v>Соколов Иван</c:v></c:pt></c:strCache></c:chartSpace>')
    assert _unknown(tmp_path, {"word/charts/chart1.xml": chart}) == ["word/charts/chart1.xml"]


def test_chartex_point_refuses(tmp_path):
    """В chartex (водопад, дерево) текст точки лежит прямо в <cx:pt>."""
    chart = ('<?xml version="1.0"?><cx:chartSpace xmlns:cx="cx"><cx:lvl>'
             '<cx:pt idx="0">ООО «Ромашка»</cx:pt></cx:lvl></cx:chartSpace>')
    assert _unknown(tmp_path, {"xl/charts/chartEx1.xml": chart}) == ["xl/charts/chartEx1.xml"]


@pytest.mark.parametrize("name", ["word/embeddings/Microsoft_Excel_Worksheet.xlsx",
                                  "ppt/embeddings/oleObject1.bin"])
def test_embedded_file_refuses(tmp_path, name):
    """Вложенный файл не XML - внутрь не заглянуть, значит и пропускать нельзя."""
    assert _unknown(tmp_path, {name: b"PK\x03\x04binary"}) == [name]


def test_empty_values_and_media_pass(tmp_path):
    """Пустые узлы и картинки - не повод для отказа."""
    chart = '<?xml version="1.0"?><c:chartSpace xmlns:c="c"><c:v/><c:v> </c:v></c:chartSpace>'
    assert _unknown(tmp_path, {"word/charts/chart1.xml": chart,
                               "word/media/image1.png": b"\x89PNG"}) == []
