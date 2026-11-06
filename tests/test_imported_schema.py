import json
from pathlib import Path

import jsonschema
import pytest


@pytest.fixture(scope="module")
def validator():
    path = Path(__file__).parent.parent / "schemas" / "campaign.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.Draft7Validator.check_schema(schema)
    return jsonschema.Draft7Validator(schema)


@pytest.fixture
def baseline():
    path = Path(__file__).parent / "fixtures" / "example.json"
    return json.loads(path.read_text(encoding="utf-8"))


def resource(baseline, level):
    campaign = baseline["campaigns"][0]
    if level == "campaign":
        return campaign
    ad_set = campaign["ad_sets"][0]
    if level == "ad_set":
        return ad_set
    return ad_set["ads"][0]


LEVELS = ("campaign", "ad_set", "ad")


def test_archived_with_ids_valid_at_all_levels(validator, baseline):
    for level in LEVELS:
        obj = resource(baseline, level)
        assert obj["fb_id"]
        obj["status"] = "ARCHIVED"
    validator.validate(baseline)


@pytest.mark.parametrize("level", LEVELS)
def test_archived_without_id_invalid(validator, baseline, level):
    obj = resource(baseline, level)
    obj["status"] = "ARCHIVED"
    del obj["fb_id"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(baseline)


@pytest.mark.parametrize("status", ("ACTIVE", "PAUSED", "ARCHIVED"))
def test_existing_ad_without_creative_valid(validator, baseline, status):
    ad = resource(baseline, "ad")
    assert ad["fb_id"]
    ad["status"] = status
    del ad["creative"]
    validator.validate(baseline)


@pytest.mark.parametrize("status", ("ACTIVE", "PAUSED"))
def test_new_ad_without_creative_invalid(validator, baseline, status):
    ad = resource(baseline, "ad")
    ad["status"] = status
    del ad["fb_id"]
    del ad["creative"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(baseline)


@pytest.mark.parametrize("status", ("ACTIVE", "PAUSED"))
def test_new_resources_with_complete_creative_valid(validator, baseline, status):
    for level in LEVELS:
        obj = resource(baseline, level)
        del obj["fb_id"]
        obj["status"] = status
    validator.validate(baseline)


@pytest.mark.parametrize("existing", (False, True))
@pytest.mark.parametrize("creative", (
    None,
    {},
    {"name": "Partial creative"},
    {"object_story_spec": {"page_id": "123"}},
    {"name": "Partial story", "object_story_spec": {}},
    {
        "name": "Partial link",
        "object_story_spec": {"page_id": "123", "link_data": {"link": "https://example.com"}},
    },
))
def test_supplied_invalid_creative_invalid(validator, baseline, existing, creative):
    ad = resource(baseline, "ad")
    if not existing:
        del ad["fb_id"]
    ad["creative"] = creative
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(baseline)


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("status", ("ACTIVE", "PAUSED", "ARCHIVED"))
@pytest.mark.parametrize("fb_id", ("", None, 123))
def test_invalid_ids_rejected(validator, baseline, level, status, fb_id):
    obj = resource(baseline, level)
    obj["status"] = status
    obj["fb_id"] = fb_id
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(baseline)


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("field", ("name", "status"))
def test_imported_resources_still_require_name_and_status(validator, baseline, level, field):
    obj = resource(baseline, level)
    del obj[field]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(baseline)


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("status", ("DELETED", "RUNNING"))
def test_unrelated_statuses_still_invalid(validator, baseline, level, status):
    resource(baseline, level)["status"] = status
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(baseline)


@pytest.mark.parametrize("level", LEVELS)
def test_unknown_properties_still_invalid(validator, baseline, level):
    resource(baseline, level)["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(baseline)
