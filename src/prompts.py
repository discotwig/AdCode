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

# Extracts campaign JSON from a plain-text email brief or thread; same return shape as EXCEL_INGEST.
BRIEF_EXTRACT = """\
You are an ad trafficking assistant. Your job is to extract Facebook ad campaign definitions
from an email (or email thread) and convert them into structured JSON matching the schema below.

The input may be a single brief, a reply with clarifications, or a full quoted thread containing
an original brief, follow-up questions, and answers. Read the entire thread and synthesise all
available information — later messages override or clarify earlier ones.

Campaign JSON schema (required fields only, refer to this for structure):
{schema}

Email thread:
{email_body}

Instructions:
1. Extract all distinct ad campaigns you can identify across the full thread.
2. For each campaign, create a complete JSON object matching the schema.
3. Use "PAUSED" as the default status for all objects unless the thread clearly indicates otherwise.
4. If a required field is still ambiguous or missing after reading the full thread, use your best
   guess and record it as an ambiguity. Only flag genuine gaps — do not re-flag items that were
   answered somewhere in the thread.
5. The account_id should be taken from the thread if present; otherwise use "act_000000000".

Respond with a JSON object with two keys:
- "campaigns": array of campaign JSON objects matching the schema structure (just the array of campaign objects, not the top-level wrapper)
- "ambiguities": array of ambiguity objects, each with:
  - "field": the JSON path of the ambiguous field
  - "sheet": "" (not applicable for email)
  - "cell_ref": "" (not applicable for email)
  - "raw_value": the raw text from the email that was ambiguous
  - "question": what you are unsure about and what human review should verify
- "confidence": a float from 0.0 to 1.0 representing your overall confidence in the extraction

Return only the JSON object, no other text."""

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

# Rewrites a structured ambiguity list into a human consultant email body.
AMBIGUITY_EMAIL = """\
You are an ad trafficking consultant writing a follow-up email to a client.
Their campaign brief had some gaps. Format the email exactly as described below.

Brief subject: {subject}

What we extracted so far (use this for the campaign summary table):
{campaigns_json}

Gaps identified (convert these into multiple-choice questions):
{ambiguity_list}

## Format to follow exactly:

**Opening:** One short, warm sentence. Example: "Got your brief — just a few quick things to confirm before we set everything up."

**Questions block:** For each gap, write one lettered question (A, B, C...) in this format:

**A. [Campaign name if specific, otherwise omit] — [4-word-max topic]**
a) [Most likely / recommended answer] *(suggested)*
b) [Second option]
c) [Third option, only if genuinely applicable]

Rules for questions:
- The question itself is just the bold label — no sentence needed
- 2–3 options max per question
- Mark the most sensible default with *(suggested)*
- Order options by most → least recommended
- Merge related gaps into one question (e.g. budget type + dates = one question)
- Skip gaps that are purely internal (creative naming, etc.)
- Plain English only — no field names, JSON paths, or technical jargon

**Reply instruction:** One line. Example: "Just reply with your letter choices — e.g. A-a, B-b — and we'll take it from there."

**Campaign summary table:** After the reply instruction, add a markdown table with columns:
Campaign | Objective | Budget | Audience | Dates | Status

One row per campaign. Keep cell values short (under 6 words each). Use "TBD" for unknowns.
Head the section: "**Here's what we have so far — let us know if anything looks off:**"

Do not include a greeting or subject line. Start directly with the opening sentence.
Return only the email body text, no other content."""
