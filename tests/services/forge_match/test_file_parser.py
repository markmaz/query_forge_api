from __future__ import annotations

from app.services.forge_match.field_extractor import ForgeMatchFieldExtractor
from app.services.forge_match.file_parser import ForgeMatchFileParser


def test_csv_parser_and_extractor_detects_field_rows() -> None:
    parser = ForgeMatchFileParser()
    extractor = ForgeMatchFieldExtractor()

    csv_bytes = (
        "Source Field Name,Description,Data Type,Source Object,Example Value\n"
        "BirthDate,Student date of birth,date,StudentDemographics,2010-02-14\n"
        "GradeLevel,Current grade,string,StudentDemographics,5\n"
    ).encode("utf-8")

    workbook = parser.parse(file_bytes=csv_bytes, filename="mapping.csv")
    assert workbook.file_type == "csv"
    assert len(workbook.sheets) == 1

    records = extractor.extract(workbook=workbook)
    assert len(records) == 2
    assert records[0].source_field_name == "BirthDate"
    assert records[0].source_type == "date"
    assert records[0].source_object_name == "StudentDemographics"
    assert records[0].row_id == "Sheet1:2"


def test_extractor_skips_junk_rows() -> None:
    parser = ForgeMatchFileParser()
    extractor = ForgeMatchFieldExtractor()

    csv_bytes = (
        "Field Name,Description\n"
        "***,section divider\n"
        "AccountName,Customer account name\n"
    ).encode("utf-8")

    workbook = parser.parse(file_bytes=csv_bytes, filename="mapping.csv")
    records = extractor.extract(workbook=workbook)
    assert len(records) == 1
    assert records[0].source_field_name == "AccountName"
