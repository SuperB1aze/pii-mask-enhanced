"""Общие части .docx и .xlsx."""
from pii_mask_enhanced.formats import office_xml


def test_empty_node_with_attributes_does_not_swallow_next():
    """<t xml:space="preserve"/> пустой - следующий узел читается сам по себе."""
    body = '<r><t xml:space="preserve"/></r><r><t>Иванов</t></r>'.encode()
    assert office_xml.runs_text(body) == "Иванов"
