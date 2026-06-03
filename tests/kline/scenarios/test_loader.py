"""Tests for scripts/kline/scenarios/loader.py — Task 1.2.

T1.2.1  Load valid fixtures → correct structure and keys
T1.2.2  Missing course_citation yaml → LoaderError with filename in message
T1.2.3  Duplicate light_id across two files → ValueError with light_id in message
T1.2.4  Empty directory / nonexistent directory → empty dict, no raise
T1.2.5  source < 5 chars → LoaderError with filename in message
T1.2.6  Invalid severity value → LoaderError with filename in message
T1.2.7  Duplicate (pattern, setup.name) → ValueError
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scripts.kline.scenarios import LoaderError, load_lights, load_playbooks

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# T1.2.1 — Load valid fixtures
# ---------------------------------------------------------------------------


class TestLoadValidFixtures:
    def test_load_playbooks_returns_correct_patterns(self, tmp_path):
        """T1.2.1a: loading two valid playbook yamls returns correct pattern keys."""
        shutil.copy(FIXTURES / "valid_playbook_bull_engulfing.yaml", tmp_path)
        shutil.copy(FIXTURES / "valid_playbook_dark_double_star.yaml", tmp_path)

        result = load_playbooks([tmp_path])

        assert "bull_engulfing" in result
        assert "dark_double_star" in result
        assert len(result["bull_engulfing"]) == 1
        assert len(result["dark_double_star"]) == 1

    def test_load_playbooks_playbook_structure(self, tmp_path):
        """T1.2.1b: loaded playbook has correct nested structure."""
        shutil.copy(FIXTURES / "valid_playbook_bull_engulfing.yaml", tmp_path)

        result = load_playbooks([tmp_path])
        pb = result["bull_engulfing"][0]

        assert pb.pattern == "bull_engulfing"
        assert pb.setup.name == "classic_bear_exhaustion"
        assert len(pb.branches) == 2
        assert pb.branches[0].id == "B1_next_day_strong"
        assert pb.branches[0].action.type == "context_only_signal"
        assert pb.branches[0].action.course_citation.source == "明日 K 線 §06 不要解讀為買點"
        assert pb.branches[1].id == "B2_next_day_weak"
        assert pb.branches[1].action.type == "stop_loss_trigger"

    def test_load_lights_returns_correct_light_ids(self, tmp_path):
        """T1.2.1c: loading a valid light yaml returns dict keyed by light_id."""
        shutil.copy(FIXTURES / "valid_light_pressure_meeting.yaml", tmp_path)

        result = load_lights([tmp_path])

        assert "pressure_meeting_unresolved" in result
        light = result["pressure_meeting_unresolved"]
        assert light.severity == "warn"
        assert light.course_citation.source == "明日 K 線 §04 遇壓未化解警示"

    def test_load_playbooks_multiple_dirs(self, tmp_path):
        """T1.2.1d: multiple dirs are scanned and merged into single result."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        shutil.copy(FIXTURES / "valid_playbook_bull_engulfing.yaml", dir1)
        shutil.copy(FIXTURES / "valid_playbook_dark_double_star.yaml", dir2)

        result = load_playbooks([dir1, dir2])

        assert "bull_engulfing" in result
        assert "dark_double_star" in result


# ---------------------------------------------------------------------------
# T1.2.2 — Missing course_citation → LoaderError with filename
# ---------------------------------------------------------------------------


class TestMissingCourseCitation:
    def test_missing_citation_raises_loader_error(self, tmp_path):
        """T1.2.2: YAML missing course_citation must raise LoaderError."""
        shutil.copy(FIXTURES / "invalid_no_citation.yaml", tmp_path)

        with pytest.raises(LoaderError) as exc_info:
            load_playbooks([tmp_path])

        # Error message must contain the filename
        assert "invalid_no_citation.yaml" in str(exc_info.value)

    def test_loader_error_contains_field_path(self, tmp_path):
        """T1.2.2b: LoaderError message should mention field path."""
        shutil.copy(FIXTURES / "invalid_no_citation.yaml", tmp_path)

        with pytest.raises(LoaderError) as exc_info:
            load_playbooks([tmp_path])

        msg = str(exc_info.value)
        # Should mention course_citation in the field path
        assert "course_citation" in msg


# ---------------------------------------------------------------------------
# T1.2.3 — Duplicate light_id → ValueError
# ---------------------------------------------------------------------------


class TestDuplicateLightId:
    def test_duplicate_light_id_raises_value_error(self, tmp_path):
        """T1.2.3: two files with same light_id must raise ValueError."""
        # Copy the same valid light file under two different names
        src = FIXTURES / "valid_light_pressure_meeting.yaml"
        shutil.copy(src, tmp_path / "light_a.yaml")
        shutil.copy(src, tmp_path / "light_b.yaml")

        with pytest.raises(ValueError) as exc_info:
            load_lights([tmp_path])

        assert "pressure_meeting_unresolved" in str(exc_info.value)

    def test_duplicate_light_error_message_contains_filename(self, tmp_path):
        """T1.2.3b: duplicate ValueError message should mention the conflicting file."""
        src = FIXTURES / "valid_light_pressure_meeting.yaml"
        shutil.copy(src, tmp_path / "light_copy1.yaml")
        shutil.copy(src, tmp_path / "light_copy2.yaml")

        with pytest.raises(ValueError) as exc_info:
            load_lights([tmp_path])

        msg = str(exc_info.value)
        # At least one of the duplicate filenames must be in the message
        assert "light_copy1.yaml" in msg or "light_copy2.yaml" in msg


# ---------------------------------------------------------------------------
# T1.2.4 — Empty / nonexistent directory → empty dict
# ---------------------------------------------------------------------------


class TestEmptyOrMissingDirs:
    def test_empty_dir_returns_empty_playbooks(self, tmp_path):
        """T1.2.4a: empty directory returns {} for playbooks without raising."""
        result = load_playbooks([tmp_path])
        assert result == {}

    def test_empty_dir_returns_empty_lights(self, tmp_path):
        """T1.2.4b: empty directory returns {} for lights without raising."""
        result = load_lights([tmp_path])
        assert result == {}

    def test_nonexistent_dir_returns_empty_playbooks(self, tmp_path):
        """T1.2.4c: nonexistent directory returns {} without raising."""
        nonexistent = tmp_path / "does_not_exist"
        result = load_playbooks([nonexistent])
        assert result == {}

    def test_nonexistent_dir_returns_empty_lights(self, tmp_path):
        """T1.2.4d: nonexistent directory returns {} without raising."""
        nonexistent = tmp_path / "does_not_exist"
        result = load_lights([nonexistent])
        assert result == {}

    def test_empty_list_of_dirs_returns_empty(self):
        """T1.2.4e: passing [] as dirs returns empty dicts."""
        assert load_playbooks([]) == {}
        assert load_lights([]) == {}


# ---------------------------------------------------------------------------
# T1.2.5 — source < 5 chars → LoaderError with filename
# ---------------------------------------------------------------------------


class TestShortSource:
    def test_short_source_playbook_raises_loader_error(self, tmp_path):
        """T1.2.5: YAML with source < 5 chars must raise LoaderError."""
        shutil.copy(FIXTURES / "invalid_short_source.yaml", tmp_path)

        with pytest.raises(LoaderError) as exc_info:
            load_playbooks([tmp_path])

        msg = str(exc_info.value)
        assert "invalid_short_source.yaml" in msg

    def test_short_source_error_mentions_field(self, tmp_path):
        """T1.2.5b: error message should mention 'source' field."""
        shutil.copy(FIXTURES / "invalid_short_source.yaml", tmp_path)

        with pytest.raises(LoaderError) as exc_info:
            load_playbooks([tmp_path])

        assert "source" in str(exc_info.value)


# ---------------------------------------------------------------------------
# T1.2.6 — Invalid severity → LoaderError with filename
# ---------------------------------------------------------------------------


class TestBadSeverity:
    def test_bad_severity_raises_loader_error(self, tmp_path):
        """T1.2.6: Light with severity='foo' must raise LoaderError."""
        shutil.copy(FIXTURES / "invalid_bad_severity.yaml", tmp_path)

        with pytest.raises(LoaderError) as exc_info:
            load_lights([tmp_path])

        msg = str(exc_info.value)
        assert "invalid_bad_severity.yaml" in msg

    def test_bad_severity_error_mentions_field(self, tmp_path):
        """T1.2.6b: error message should mention 'severity' field."""
        shutil.copy(FIXTURES / "invalid_bad_severity.yaml", tmp_path)

        with pytest.raises(LoaderError) as exc_info:
            load_lights([tmp_path])

        assert "severity" in str(exc_info.value)


# ---------------------------------------------------------------------------
# T1.2.7 — Duplicate (pattern, setup.name) → ValueError
# ---------------------------------------------------------------------------


class TestDuplicatePlaybookKey:
    def test_duplicate_pattern_setup_raises_value_error(self, tmp_path):
        """T1.2.7: two files with same (pattern, setup.name) must raise ValueError."""
        src = FIXTURES / "valid_playbook_bull_engulfing.yaml"
        shutil.copy(src, tmp_path / "pb_copy1.yaml")
        shutil.copy(src, tmp_path / "pb_copy2.yaml")

        with pytest.raises(ValueError) as exc_info:
            load_playbooks([tmp_path])

        msg = str(exc_info.value)
        # Should mention the pattern and setup name
        assert "bull_engulfing" in msg
        assert "classic_bear_exhaustion" in msg
