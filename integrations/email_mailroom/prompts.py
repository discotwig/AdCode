# Prompt templates used only by the email mailroom integration.

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
- 2-3 options max per question
- Mark the most sensible default with *(suggested)*
- Order options by most -> least recommended
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
