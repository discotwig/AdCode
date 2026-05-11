import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

import openpyxl

from src.services.ingest import (
    read_excel, extract_campaigns, format_ambiguity_report,
    IngestionResult, Ambiguity,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_excel(tmp_path: Path, sheet_data: dict) -> str:
    wb = openpyxl.Workbook()
    first = True
    for sheet_name, rows in sheet_data.items():
        if first:
            ws = wb.active
            ws.title = sheet_name
            first = False
        else:
            ws = wb.create_sheet(sheet_name)
        for row in rows:
            ws.append(row)
    path = str(tmp_path / "test.xlsx")
    wb.save(path)
    return path


def _make_ai_client(campaigns: list, ambiguities: list, confidence: float = 0.9) -> MagicMock:
    client = MagicMock()
    content = MagicMock()
    content.text = json.dumps({"campaigns": campaigns, "ambiguities": ambiguities, "confidence": confidence})
    client.messages.create.return_value.content = [content]
    return client


# ------------------------------------------------------------------
# read_excel
# ------------------------------------------------------------------

class TestReadExcel:
    def test_reads_single_sheet(self, tmp_path):
        path = _make_excel(tmp_path, {
            "Campaigns": [
                ["Campaign Name", "Objective", "Status"],
                ["Summer Sale", "OUTCOME_TRAFFIC", "PAUSED"],
            ]
        })
        result = read_excel(path)
        assert "Campaigns" in result

    def test_parses_headers_from_first_row(self, tmp_path):
        path = _make_excel(tmp_path, {
            "Sheet1": [
                ["Name", "Budget"],
                ["Camp A", 5000],
            ]
        })
        result = read_excel(path)
        assert result["Sheet1"]["headers"] == ["Name", "Budget"]

    def test_parses_data_rows_as_dicts(self, tmp_path):
        path = _make_excel(tmp_path, {
            "Sheet1": [
                ["Name", "Budget"],
                ["Camp A", 5000],
                ["Camp B", 3000],
            ]
        })
        result = read_excel(path)
        assert len(result["Sheet1"]["rows"]) == 2
        assert result["Sheet1"]["rows"][0]["Name"] == "Camp A"

    def test_reads_multiple_sheets(self, tmp_path):
        path = _make_excel(tmp_path, {
            "Campaigns": [["Name"], ["Camp A"]],
            "Ad Sets": [["Name"], ["US 25-54"]],
        })
        result = read_excel(path)
        assert "Campaigns" in result
        assert "Ad Sets" in result

    def test_skips_empty_sheets(self, tmp_path):
        path = _make_excel(tmp_path, {
            "Populated": [["Name"], ["Camp A"]],
            "Empty": [],
        })
        result = read_excel(path)
        assert "Populated" in result
        assert "Empty" not in result

    def test_handles_none_cells_in_header(self, tmp_path):
        path = _make_excel(tmp_path, {
            "Sheet1": [
                ["Name", None, "Budget"],
                ["Camp A", None, 5000],
            ]
        })
        result = read_excel(path)
        assert len(result["Sheet1"]["headers"]) == 3


# ------------------------------------------------------------------
# extract_campaigns
# ------------------------------------------------------------------

class TestExtractCampaigns:
    def test_returns_ingestion_result(self):
        ai_client = _make_ai_client(campaigns=[], ambiguities=[])
        result = extract_campaigns({"Sheet1": {"headers": [], "rows": [], "raw_rows": []}}, ai_client)
        assert isinstance(result, IngestionResult)

    def test_campaigns_extracted_from_ai_response(self):
        campaigns = [{"name": "Summer Sale", "objective": "OUTCOME_TRAFFIC"}]
        ai_client = _make_ai_client(campaigns=campaigns, ambiguities=[])
        result = extract_campaigns({}, ai_client)
        assert len(result.campaigns) == 1
        assert result.campaigns[0]["name"] == "Summer Sale"

    def test_ambiguities_extracted_from_ai_response(self):
        ambiguity = {
            "field": "campaigns[0].objective",
            "sheet": "Sheet1",
            "cell_ref": "B2",
            "raw_value": "Traffic",
            "question": "Is this OUTCOME_TRAFFIC or OUTCOME_AWARENESS?",
        }
        ai_client = _make_ai_client(campaigns=[], ambiguities=[ambiguity])
        result = extract_campaigns({}, ai_client)
        assert len(result.ambiguities) == 1
        assert isinstance(result.ambiguities[0], Ambiguity)
        assert result.ambiguities[0].cell_ref == "B2"

    def test_confidence_extracted_from_ai_response(self):
        ai_client = _make_ai_client(campaigns=[], ambiguities=[], confidence=0.75)
        result = extract_campaigns({}, ai_client)
        assert result.confidence == 0.75

    def test_non_json_response_returns_empty_result(self):
        ai_client = MagicMock()
        content = MagicMock()
        content.text = "I cannot process this file."
        ai_client.messages.create.return_value.content = [content]
        result = extract_campaigns({}, ai_client)
        assert result.campaigns == []
        assert result.confidence == 0.0

    def test_ai_client_is_called(self):
        ai_client = _make_ai_client(campaigns=[], ambiguities=[])
        extract_campaigns({"Sheet1": {}}, ai_client)
        ai_client.messages.create.assert_called_once()

    def test_malformed_ambiguity_items_are_skipped(self):
        raw = json.dumps({
            "campaigns": [],
            "ambiguities": [
                None,
                {"field": "x", "sheet": "s", "cell_ref": "", "raw_value": "v", "question": "q"},
            ],
            "confidence": 0.8,
        })
        ai_client = MagicMock()
        content = MagicMock()
        content.text = raw
        ai_client.messages.create.return_value.content = [content]
        result = extract_campaigns({}, ai_client)
        assert len(result.ambiguities) == 1


# ------------------------------------------------------------------
# format_ambiguity_report
# ------------------------------------------------------------------

class TestFormatAmbiguityReport:
    def test_no_ambiguities_message(self):
        result = IngestionResult(campaigns=[{}], ambiguities=[], confidence=0.95)
        text = format_ambiguity_report(result)
        assert "No ambiguities" in text
        assert "1 campaign" in text

    def test_ambiguity_count_in_output(self):
        ambiguities = [
            Ambiguity(field="f1", sheet="s1", cell_ref="A1", raw_value="x", question="q1"),
            Ambiguity(field="f2", sheet="s2", cell_ref="B2", raw_value="y", question="q2"),
        ]
        result = IngestionResult(campaigns=[], ambiguities=ambiguities, confidence=0.6)
        text = format_ambiguity_report(result)
        assert "2" in text

    def test_ambiguity_details_in_output(self):
        ambiguities = [
            Ambiguity(field="campaigns[0].objective", sheet="Campaigns", cell_ref="C3",
                      raw_value="Traffic", question="OUTCOME_TRAFFIC or OUTCOME_AWARENESS?"),
        ]
        result = IngestionResult(campaigns=[], ambiguities=ambiguities, confidence=0.7)
        text = format_ambiguity_report(result)
        assert "campaigns[0].objective" in text
        assert "Traffic" in text
        assert "OUTCOME_TRAFFIC or OUTCOME_AWARENESS?" in text

    def test_confidence_shown_in_output(self):
        result = IngestionResult(campaigns=[], ambiguities=[], confidence=0.85)
        text = format_ambiguity_report(result)
        assert "85%" in text
