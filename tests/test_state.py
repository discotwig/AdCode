import json
import pytest
from pathlib import Path
from unittest.mock import patch

from src.services.state import StateFile


@pytest.fixture
def empty_state():
    return StateFile("act_123456789")


@pytest.fixture
def populated_state():
    s = StateFile("act_123456789")
    s.upsert_campaign("Summer Sale", "camp_001", {"name": "Summer Sale", "objective": "OUTCOME_TRAFFIC"})
    s.upsert_adset("Summer Sale", "US 25-54", "adset_001", {"name": "US 25-54"})
    s.upsert_ad("Summer Sale", "US 25-54", "Creative v1", "ad_001", "creative_001", {"name": "Creative v1"})
    return s


class TestLoad:
    def test_load_returns_empty_state_when_file_missing(self, tmp_path):
        with patch("src.services.state.STATE_DIR", tmp_path):
            state = StateFile.load("act_nonexistent")
        assert state.account_id == "act_nonexistent"
        assert state.campaigns() == {}

    def test_load_reads_existing_file(self, tmp_path):
        data = {
            "account_id": "act_123",
            "last_pushed_at": "2026-05-11T10:00:00+00:00",
            "campaigns": {
                "My Campaign": {
                    "fb_id": "camp_001",
                    "params": {"name": "My Campaign"},
                    "ad_sets": {}
                }
            }
        }
        (tmp_path / "act_123.json").write_text(json.dumps(data))
        with patch("src.services.state.STATE_DIR", tmp_path):
            state = StateFile.load("act_123")
        assert state.get_campaign_id("My Campaign") == "camp_001"


class TestSave:
    def test_save_creates_file(self, tmp_path, empty_state):
        with patch("src.services.state.STATE_DIR", tmp_path):
            empty_state.save()
        assert (tmp_path / "act_123456789.json").exists()

    def test_save_round_trip(self, tmp_path, populated_state):
        with patch("src.services.state.STATE_DIR", tmp_path):
            populated_state.save()
            loaded = StateFile.load("act_123456789")
        assert loaded.get_campaign_id("Summer Sale") == "camp_001"
        assert loaded.get_adset_id("Summer Sale", "US 25-54") == "adset_001"
        assert loaded.get_ad_id("Summer Sale", "US 25-54", "Creative v1") == "ad_001"

    def test_save_sets_last_pushed_at(self, tmp_path, empty_state):
        with patch("src.services.state.STATE_DIR", tmp_path):
            empty_state.save()
            loaded = StateFile.load("act_123456789")
        assert loaded.to_dict()["last_pushed_at"] != ""

    def test_save_is_atomic_no_tmp_file_left(self, tmp_path, empty_state):
        with patch("src.services.state.STATE_DIR", tmp_path):
            empty_state.save()
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []


class TestGetters:
    def test_get_campaign_id_returns_id(self, populated_state):
        assert populated_state.get_campaign_id("Summer Sale") == "camp_001"

    def test_get_campaign_id_returns_none_for_missing(self, empty_state):
        assert empty_state.get_campaign_id("Nonexistent") is None

    def test_get_adset_id_returns_id(self, populated_state):
        assert populated_state.get_adset_id("Summer Sale", "US 25-54") == "adset_001"

    def test_get_adset_id_returns_none_for_missing_campaign(self, empty_state):
        assert empty_state.get_adset_id("No Campaign", "No AdSet") is None

    def test_get_adset_id_returns_none_for_missing_adset(self, populated_state):
        assert populated_state.get_adset_id("Summer Sale", "Nonexistent AdSet") is None

    def test_get_ad_id_returns_id(self, populated_state):
        assert populated_state.get_ad_id("Summer Sale", "US 25-54", "Creative v1") == "ad_001"

    def test_get_ad_id_returns_none_for_missing(self, empty_state):
        assert empty_state.get_ad_id("A", "B", "C") is None

    def test_get_campaign_params_returns_params(self, populated_state):
        params = populated_state.get_campaign_params("Summer Sale")
        assert params["objective"] == "OUTCOME_TRAFFIC"

    def test_get_adset_params_returns_params(self, populated_state):
        params = populated_state.get_adset_params("Summer Sale", "US 25-54")
        assert params["name"] == "US 25-54"

    def test_get_ad_params_returns_params(self, populated_state):
        params = populated_state.get_ad_params("Summer Sale", "US 25-54", "Creative v1")
        assert params["name"] == "Creative v1"


class TestUpserts:
    def test_upsert_campaign_creates_entry(self, empty_state):
        empty_state.upsert_campaign("New Camp", "camp_999", {"name": "New Camp"})
        assert empty_state.get_campaign_id("New Camp") == "camp_999"

    def test_upsert_campaign_preserves_existing_adsets(self, populated_state):
        populated_state.upsert_campaign("Summer Sale", "camp_001_new", {"name": "Summer Sale Updated"})
        assert populated_state.get_adset_id("Summer Sale", "US 25-54") == "adset_001"

    def test_upsert_adset_creates_entry(self, populated_state):
        populated_state.upsert_adset("Summer Sale", "UK 18-34", "adset_002", {"name": "UK 18-34"})
        assert populated_state.get_adset_id("Summer Sale", "UK 18-34") == "adset_002"

    def test_upsert_adset_preserves_existing_ads(self, populated_state):
        populated_state.upsert_adset("Summer Sale", "US 25-54", "adset_001", {"name": "Updated"})
        assert populated_state.get_ad_id("Summer Sale", "US 25-54", "Creative v1") == "ad_001"

    def test_upsert_ad_creates_entry(self, populated_state):
        populated_state.upsert_ad("Summer Sale", "US 25-54", "Creative v2", "ad_002", "creative_002", {})
        assert populated_state.get_ad_id("Summer Sale", "US 25-54", "Creative v2") == "ad_002"

    def test_upsert_ad_stores_creative_id(self, empty_state):
        empty_state.upsert_campaign("Camp", "c1", {})
        empty_state.upsert_adset("Camp", "AdSet", "a1", {})
        empty_state.upsert_ad("Camp", "AdSet", "Ad", "ad_001", "creative_999", {})
        data = empty_state.to_dict()
        assert data["campaigns"]["Camp"]["ad_sets"]["AdSet"]["ads"]["Ad"]["creative_id"] == "creative_999"


class TestToDict:
    def test_to_dict_returns_serialisable_dict(self, populated_state):
        d = populated_state.to_dict()
        assert d["account_id"] == "act_123456789"
        assert "campaigns" in d
        serialised = json.dumps(d)
        assert "Summer Sale" in serialised


class TestStackName:
    def test_load_uses_stack_name_for_path(self, tmp_path):
        data = {
            "account_id": "act_123",
            "last_pushed_at": "",
            "campaigns": {"My Campaign": {"fb_id": "c1", "params": {}, "ad_sets": {}}}
        }
        (tmp_path / "my_stack.json").write_text(json.dumps(data))
        with patch("src.services.state.STATE_DIR", tmp_path):
            state = StateFile.load("act_123", stack_name="my_stack")
        assert state.get_campaign_id("My Campaign") == "c1"

    def test_load_ignores_account_id_file_when_stack_name_given(self, tmp_path):
        data_account = {
            "account_id": "act_123",
            "last_pushed_at": "",
            "campaigns": {"Account Campaign": {"fb_id": "old", "params": {}, "ad_sets": {}}}
        }
        data_stack = {
            "account_id": "act_123",
            "last_pushed_at": "",
            "campaigns": {"Stack Campaign": {"fb_id": "new", "params": {}, "ad_sets": {}}}
        }
        (tmp_path / "act_123.json").write_text(json.dumps(data_account))
        (tmp_path / "my_stack.json").write_text(json.dumps(data_stack))
        with patch("src.services.state.STATE_DIR", tmp_path):
            state = StateFile.load("act_123", stack_name="my_stack")
        assert state.get_campaign_id("Stack Campaign") == "new"
        assert state.get_campaign_id("Account Campaign") is None

    def test_save_uses_stack_name_for_path(self, tmp_path):
        state = StateFile("act_123", stack_name="my_stack")
        state.upsert_campaign("My Campaign", "c1", {"name": "My Campaign"})
        with patch("src.services.state.STATE_DIR", tmp_path):
            state.save()
        assert (tmp_path / "my_stack.json").exists()
        assert not (tmp_path / "act_123.json").exists()

    def test_two_stacks_same_account_are_independent(self, tmp_path):
        stack_a = StateFile("act_123", stack_name="q2_brand")
        stack_a.upsert_campaign("Brand Campaign", "c1", {"name": "Brand Campaign"})

        stack_b = StateFile("act_123", stack_name="q2_retail")
        stack_b.upsert_campaign("Retail Campaign", "c2", {"name": "Retail Campaign"})

        with patch("src.services.state.STATE_DIR", tmp_path):
            stack_a.save()
            stack_b.save()

        assert (tmp_path / "q2_brand.json").exists()
        assert (tmp_path / "q2_retail.json").exists()

        with patch("src.services.state.STATE_DIR", tmp_path):
            loaded_a = StateFile.load("act_123", stack_name="q2_brand")
            loaded_b = StateFile.load("act_123", stack_name="q2_retail")

        assert loaded_a.get_campaign_id("Brand Campaign") == "c1"
        assert loaded_a.get_campaign_id("Retail Campaign") is None
        assert loaded_b.get_campaign_id("Retail Campaign") == "c2"
        assert loaded_b.get_campaign_id("Brand Campaign") is None
