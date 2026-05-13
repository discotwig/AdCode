# Centralised prompt templates. Variables use {name} .format() syntax.

# Checks campaign JSON against Facebook ad policies; returns a JSON array of warnings.
POLICY_REVIEW = """\
You are a Facebook Ads policy reviewer. Review the following campaign JSON and identify any content
that may violate Facebook's advertising policies or be likely to cause ad rejection.

Check for:
1. Prohibited content categories: financial products with misleading claims, health/medical claims,
   adult content, political content, gambling, weapons, drugs, or tobacco.
2. Special Ad Category triggers: employment, housing, credit, or political content that requires
   declaring a Special Ad Category but has an empty special_ad_categories array.
3. Copy patterns that frequently cause rejection: superlative claims ("best", "#1", "guaranteed"),
   before/after language, personal attribute targeting implications, clickbait.
4. Landing page issues: URLs that appear to lead to prohibited content or are clearly placeholder values.
5. Missing or placeholder fields: page_id set to "REPLACE_WITH_PAGE_ID", account_id "act_000000000".

Respond with a JSON array of policy warnings. Each warning must have these fields:
- severity: "ERROR" (likely rejection), "WARNING" (possible rejection), or "INFO" (note)
- field: the JSON path to the problematic field (e.g. "campaigns[0].ad_sets[0].ads[0].creative.object_story_spec.link_data.message")
- message: a concise description of the issue
- suggestion: what to change to fix it

If there are no issues, return an empty array [].

Campaign JSON:
{campaign_json}

Return only the JSON array, no other text."""

# Extracts campaign JSON from a raw Excel structure; returns campaigns, ambiguities, and confidence.
EXCEL_INGEST = """\
You are an ad trafficking assistant. Your job is to extract Facebook ad campaign definitions
from an Excel file and convert them into structured JSON matching the schema below.

The Excel file is non-standard and may have merged cells, colour-coded rows, multi-sheet layouts,
or non-standard column names. Use your best judgement to interpret the content.

Campaign JSON schema (required fields only, refer to this for structure):
{schema}

Excel file contents:
{excel_data}

Instructions:
1. Extract all distinct ad campaigns you can identify.
2. For each campaign, create a complete JSON object matching the schema.
3. Use "PAUSED" as the default status for all objects unless the Excel clearly indicates otherwise.
4. If a required field is ambiguous or missing, use your best guess and record it as an ambiguity.
5. Do NOT include account_id in your output and do NOT flag it as an ambiguity — it is supplied externally and will be set by the system.

Respond with a JSON object with two keys:
- "campaigns": array of campaign JSON objects matching the schema structure (just the array of campaign objects, not the top-level wrapper)
- "ambiguities": array of ambiguity objects, each with:
  - "field": the JSON path of the ambiguous field
  - "sheet": the Excel sheet name where the issue was found
  - "cell_ref": the cell reference (e.g. "B5") if identifiable, otherwise ""
  - "raw_value": the raw value from Excel that was ambiguous
  - "question": what you are unsure about and what human review should verify
- "confidence": a float from 0.0 to 1.0 representing your overall confidence in the extraction

Return only the JSON object, no other text."""
