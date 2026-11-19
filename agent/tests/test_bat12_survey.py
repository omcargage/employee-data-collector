"""Unit tests for BAT-12 Burnout Assessment Tool survey module."""
import json
import pytest
from datetime import date
from edc_agent.privacy.self_report import (
    BAT12_QUESTIONS,
    compute_bat12_scores,
    record_bat12_checkin,
    get_bat12_for_day,
    get_all_bat12_by_day,
)
from edc_agent.storage.database import Database


def test_bat12_question_count_and_dimensions():
    """Verify BAT-12 has 12 items spanning all 4 core dimensions."""
    assert len(BAT12_QUESTIONS) == 12
    dims = [q["dimension"] for q in BAT12_QUESTIONS]
    assert dims.count("exhaustion") == 3
    assert dims.count("mental_distance") == 3
    assert dims.count("emotional_impairment") == 3
    assert dims.count("cognitive_impairment") == 3


def test_bat12_scoring_healthy_ratings():
    """Verify that all 1s produces lowest score (1.0) and Green status."""
    healthy_items = {f"bat_q{i}": 1 for i in range(1, 13)}
    summary = compute_bat12_scores(healthy_items, logical_day=date(2026, 11, 1))

    assert summary.total_bat_score == 1.0
    assert summary.exhaustion_score == 1.0
    assert summary.mental_distance_score == 1.0
    assert summary.emotional_impairment_score == 1.0
    assert summary.cognitive_impairment_score == 1.0
    assert summary.clinical_status == "Green"
    assert summary.verified_stressed_day is False


def test_bat12_scoring_severe_burnout_ratings():
    """Verify that high ratings produce Red clinical status and verified stress flag."""
    severe_items = {f"bat_q{i}": 5 for i in range(1, 13)}
    summary = compute_bat12_scores(severe_items, logical_day=date(2026, 11, 2))

    assert summary.total_bat_score == 5.0
    assert summary.exhaustion_score == 5.0
    assert summary.clinical_status == "Red"
    assert summary.verified_stressed_day is True


def test_bat12_clinical_cutoff_thresholds():
    """Test clinical cutoff classification logic according to BAT norms."""
    # Test Yellow: score ~ 2.75
    yellow_items = {f"bat_q{i}": (3 if i <= 9 else 2) for i in range(1, 13)}
    s_yellow = compute_bat12_scores(yellow_items)
    assert 2.59 <= s_yellow.total_bat_score < 3.02
    assert s_yellow.clinical_status == "Yellow"

    # Test Orange: score ~ 3.33
    orange_items = {f"bat_q{i}": (4 if i <= 4 else 3) for i in range(1, 13)}
    s_orange = compute_bat12_scores(orange_items)
    assert 3.02 <= s_orange.total_bat_score < 3.65
    assert s_orange.clinical_status == "Orange"
    assert s_orange.verified_stressed_day is True


def test_bat12_invalid_rating_rejection():
    """Verify rejection of invalid ratings (< 1 or > 5 or non-integer)."""
    bad_items = {f"bat_q{i}": 1 for i in range(1, 13)}
    bad_items["bat_q1"] = 6
    with pytest.raises(ValueError, match="between 1 and 5"):
        compute_bat12_scores(bad_items)

    missing_items = {f"bat_q{i}": 1 for i in range(1, 12)}  # missing q12
    with pytest.raises(ValueError, match="Missing required BAT-12 item"):
        compute_bat12_scores(missing_items)


def test_record_and_retrieve_bat12_database(tmp_path):
    """Verify storage in SQLite database and subsequent retrieval."""
    db_file = tmp_path / "test_edc.db"
    db = Database(db_file)

    target_day = date(2026, 11, 15)
    items = {f"bat_q{i}": (2 if i <= 6 else 3) for i in range(1, 13)}

    summary = record_bat12_checkin(db, target_day, items=items)
    assert summary.logical_day == "2026-11-15"

    retrieved = get_bat12_for_day(db, target_day)
    assert retrieved is not None
    assert retrieved.logical_day == "2026-11-15"
    assert retrieved.total_bat_score == summary.total_bat_score
    assert retrieved.items["bat_q1"] == 2
    assert retrieved.items["bat_q12"] == 3

    all_checkins = get_all_bat12_by_day(db)
    assert "2026-11-15" in all_checkins
    assert all_checkins["2026-11-15"].clinical_status == summary.clinical_status
