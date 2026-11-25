import pytest

from app.evaluation import summarize


def test_missing_and_repeated_measurements_have_explicit_denominators(tmp_path):
    source = tmp_path / "technical_fixture.csv"
    source.write_text(
        "participant_id,task_id,success,seconds,comprehension,actionability\nunit-a,locate,1,10,5,\nunit-b,locate,0,20,3,2\n",
        encoding="utf8",
    )
    result = summarize(source)
    m = result["tasks"]["locate"]["measures"]
    assert result["participants"] == 2
    assert m["success"]["mean"] == 0.5
    assert m["seconds"]["median"] == 15
    assert m["actionability"]["n"] == 1 and m["actionability"]["missing"] == 1


@pytest.mark.parametrize(
    "row", ["x,t,1,nan,3,2", "x,t,2,10,3,2", "x,t,1,10,6,2", ",t,1,10,3,2"]
)
def test_invalid_session_rows_rejected(tmp_path, row):
    source = tmp_path / "fixture.csv"
    source.write_text(
        "participant_id,task_id,success,seconds,comprehension,actionability\n" + row,
        encoding="utf8",
    )
    with pytest.raises(ValueError):
        summarize(source)
