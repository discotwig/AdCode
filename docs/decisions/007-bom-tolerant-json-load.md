# ADR-007 — BOM-Tolerant JSON Loading

**Status:** Accepted  
**Date:** 2026-05-12

---

## Context

`plan_campaigns` and `apply_campaigns` call `load_campaign_json` (traffic.py) to read a campaign JSON file from disk. ADR-006 pinned all file I/O to `encoding="utf-8"` to prevent CP1252 mis-decoding on Windows. That fix handles files written without a byte-order mark.

A second class of Windows-produced files also exists: editors such as Notepad and VS Code (when configured to do so) emit a UTF-8 BOM (`\xef\xbb\xbf`) at the start of the file. Python's `json` module does not strip the BOM before parsing, so `json.load` raises a `JSONDecodeError` ("Unexpected UTF-8 BOM") even though the file content is otherwise valid JSON. The `demo_v1.json` demo file triggered this failure when passed to `plan_campaigns`.

---

## Decisions

### 1. Use `utf-8-sig` in `load_campaign_json`

Change the `open()` call in `load_campaign_json` from `encoding="utf-8"` to `encoding="utf-8-sig"`. Python's `utf-8-sig` codec strips a leading BOM when reading and is otherwise identical to `utf-8` — no data loss, no behaviour change for BOM-free files.

**Rationale:** The fix is one character. It makes the reader tolerant of both BOM and non-BOM UTF-8 files without requiring callers to pre-process inputs or editors to be reconfigured. All write paths continue to use `encoding="utf-8"` (no BOM on output), so files written by AdCode are always clean.

### 2. Strip the BOM from `demo_v1.json`

Remove the BOM from the committed demo file so it validates cleanly without relying on the `utf-8-sig` fix being in force.

**Rationale:** Source files in the repo should be BOM-free. The demo file is the canonical example shown to new users and used in `plan_campaigns` walkthroughs — it should pass validation out of the box on any toolchain, including environments that have not yet picked up the `utf-8-sig` reader fix.

---

## Consequences

**Positive:**
- `plan_campaigns` and `apply_campaigns` accept BOM-marked JSON files without error.
- No change to any write path — files AdCode writes are always BOM-free UTF-8.
- The demo file validates cleanly.

**Negative:**
- None. `utf-8-sig` is a strict superset of `utf-8` for reading.

---

## Files changed

| File | Change |
|---|---|
| `src/traffic.py` | `load_campaign_json`: `encoding="utf-8"` → `encoding="utf-8-sig"` |
| `campaigns/demo/act_000000000/demo_v1.json` | BOM stripped |
