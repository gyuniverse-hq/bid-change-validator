from io import BytesIO

import pytest

from apps.api.app.services.document_extraction import (
    UnsupportedDocumentError,
    extract_document,
)


def test_hwp_extension_with_hwpml_xml_is_extracted() -> None:
    source = BytesIO(
        """<?xml version="1.0" encoding="UTF-8"?>
        <HWPML Version="2.8">
          <BODY>
            <SECTION Id="0">
              <P><TEXT><CHAR>입찰 참가자격<TAB/>중소기업</CHAR></TEXT></P>
              <P><TEXT><CHAR>실적 4억원<LINEBREAK/>이상</CHAR></TEXT></P>
            </SECTION>
          </BODY>
        </HWPML>
        """.encode("utf-8")
    )

    result = extract_document(
        source,
        filename="공고문.hwp",
        content_type="application/x-hwp",
    )

    assert result.extractor == "HWPML_XML"
    assert result.text == "입찰 참가자격 중소기업\n\n실적 4억원\n이상"
    assert result.blocks[1]["location"] == "section 1 · paragraph 2"


def test_non_hwpml_xml_with_hwp_extension_is_rejected() -> None:
    with pytest.raises(UnsupportedDocumentError, match="not HWPML"):
        extract_document(
            BytesIO(b"<?xml version='1.0'?><root><P>not hwpml</P></root>"),
            filename="fake.hwp",
            content_type="application/x-hwp",
        )
