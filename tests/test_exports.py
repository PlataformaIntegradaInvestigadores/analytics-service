"""Import boundaries, explicit mapping and file-wide deduplication."""

import csv
import json

import pytest

from app.data.exports import inspect_export
from app.domain.common import AnalyticsError
from app.imports import main


def jsonl(tmp_path, rows):
    path = tmp_path / "export.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def test_jsonl_batches_deduplicate_file_wide(tmp_path, record):
    path = jsonl(tmp_path, [record(), record(), record("other")])
    result = inspect_export(path, "jsonl", "synthetic", batch_size=1)
    assert result["status"] == "compatible"
    assert len(result["manifest"]["batches"]) == 3
    assert result["curation"]["quality"]["duplicate_rows"] == 1
    assert result["curation"]["quality"]["accepted_documents"] == 2
    assert "abstract" in result["missing_optional_fields"]
    assert inspect_export(path, "jsonl", "synthetic", batch_size=1) == result


def test_csv_mapping_keywords_and_unknown_availability(tmp_path, record):
    path = tmp_path / "export.csv"
    row = record(keywords=["topic"], abstract=None, access="")
    row = {
        ("id" if key == "source_id" else key): (
            json.dumps(value) if key == "keywords" else "" if value is None else value
        )
        for key, value in row.items()
    }
    row["available_on"] = ""
    row["ignored"] = "extra"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    mapping = {
        key: "id" if key == "source_id" else key
        for key in record(keywords=[], abstract=None, access="")
    }
    result = inspect_export(path, "csv", "synthetic", mapping, ["ignored"])
    doc = result["curation"]["documents"][0]
    assert doc["keywords"] == ["topic"]
    assert doc["available_on"] is None
    assert doc["provenance"][0]["access"] == "unknown"


@pytest.mark.parametrize(
    "options,code",
    [
        ({"file_format": "xml"}, "invalid_export_format"),
        ({"batch_size": 0}, "invalid_batch_size"),
        ({"batch_size": True}, "invalid_batch_size"),
        ({"mapping": {}}, "invalid_field_mapping"),
        (
            {
                "mapping": {
                    "source": "x",
                    "source_id": "x",
                    "title": "t",
                    "retrieved_at": "r",
                }
            },
            "invalid_field_mapping",
        ),
        (
            {
                "mapping": {
                    "source": "s",
                    "source_id": "i",
                    "title": "t",
                    "retrieved_at": " ",
                }
            },
            "invalid_field_mapping",
        ),
        ({"ignored_columns": ["source"]}, "invalid_field_mapping"),
    ],
)
def test_invalid_import_configuration(tmp_path, record, options, code):
    with pytest.raises(AnalyticsError) as exc:
        inspect_export(
            **{
                "path": jsonl(tmp_path, [record()]),
                "file_format": "jsonl",
                "data_kind": "synthetic",
                **options,
            }
        )
    assert exc.value.code == code


@pytest.mark.parametrize(
    "content,format,code",
    [
        ("", "jsonl", "empty_export"),
        ("\n", "jsonl", "invalid_export"),
        ("[]\n", "jsonl", "invalid_export"),
        ('{"title":1,"title":2}', "jsonl", "invalid_json"),
        ("", "csv", "invalid_export"),
        ("a,a\n1,2", "csv", "invalid_export"),
        ("a,\n1,2", "csv", "invalid_export"),
        ("a,b\n1,2,3", "csv", "invalid_export"),
        ("a,b\n1", "csv", "invalid_export"),
        ('a,b\n"broken', "csv", "invalid_export"),
        ("source,source_id,title,retrieved_at\n", "csv", "empty_export"),
        ("{}\n", "jsonl", "incompatible_export_fields"),
    ],
)
def test_malformed_export_diagnostics(tmp_path, content, format, code):
    path = tmp_path / "export"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(AnalyticsError) as exc:
        inspect_export(path, format, "synthetic")
    assert exc.value.code == code


def test_encoding_size_and_row_limits(tmp_path, record):
    path = tmp_path / "input"
    path.write_bytes(b"\xff")
    with pytest.raises(AnalyticsError, match="UTF-8"):
        inspect_export(path, "jsonl", "synthetic")
    path.write_bytes(b" " * (8 * 1024 * 1024 + 1))
    with pytest.raises(AnalyticsError, match="bounded import"):
        inspect_export(path, "csv", "synthetic")
    path = jsonl(tmp_path, [record()] * 1001)
    with pytest.raises(AnalyticsError, match="1000 rows"):
        inspect_export(path, "jsonl", "synthetic")
    path.write_text(
        "source,source_id,title,retrieved_at\n" + "s,i,t,r\n" * 1001, encoding="utf-8"
    )
    with pytest.raises(AnalyticsError, match="1000 rows"):
        inspect_export(path, "csv", "synthetic")


def test_unmapped_fields_and_rejected_rows(tmp_path, record):
    path = jsonl(tmp_path, [record(unmapped="extra")])
    with pytest.raises(AnalyticsError, match="Explicitly map"):
        inspect_export(path, "jsonl", "synthetic")
    result = inspect_export(path, "jsonl", "synthetic", ignored_columns=["unmapped"])
    assert result["status"] == "compatible"
    path = jsonl(tmp_path, [record(title="")])
    assert inspect_export(path, "jsonl", "synthetic")["status"] == "needs_correction"


def test_csv_empty_keywords(tmp_path, record):
    path = tmp_path / "input.csv"
    row = record(keywords="")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, list(row))
        writer.writeheader()
        writer.writerow(row)
    assert (
        inspect_export(path, "csv", "synthetic")["curation"]["documents"][0]["keywords"]
        == []
    )


def test_import_cli_dictionary_mapping_and_exit_codes(tmp_path, record, capsys):
    assert main(["dictionary"]) == 0
    assert json.loads(capsys.readouterr().out)["limits"]["rows"] == 1000
    assert main(["dictionary", "--input", "x"]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "invalid_arguments"
    assert main(["inspect"]) == 2
    capsys.readouterr()
    path = jsonl(tmp_path, [record()])
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps({"fields": {field: field for field in record()}}), encoding="utf-8"
    )
    args = [
        "inspect",
        "--input",
        str(path),
        "--format",
        "jsonl",
        "--data-kind",
        "synthetic",
        "--mapping",
        str(mapping),
    ]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "compatible"
    path = jsonl(tmp_path, [record(title="")])
    assert main(args) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "needs_correction"
    assert main([*args, "--batch-size", "0"]) == 2
    capsys.readouterr()
    mapping.write_text("{}", encoding="utf-8")
    assert main(args) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "invalid_input"
