# Meta (Facebook) Marketing API — Research Notes

## Overview

The Facebook Marketing API is a Graph API surface for programmatically creating, reading, updating, and deleting ad campaigns. It uses OAuth 2.0 for authentication and returns JSON. Rate limits are enforced at the ad account level. The API version is specified in the URL path; older versions are deprecated on a rolling schedule.

**Base URL:** `https://graph.facebook.com/v{version}/`

**Authentication:** Long-lived user access token or system user token scoped to the ad account. System user tokens are preferred for server-side integrations — they are not tied to a person's Facebook account and do not expire on the same schedule as user tokens.

**Python SDK:** `facebook-business` (maintained by Meta). Wraps the Graph API with typed objects for campaigns, ad sets, and ads. Recommended over raw HTTP for this project.

```
pip install facebook-business
```

---

## Campaign Object Model

Facebook's ad structure is a strict three-level hierarchy:

```
Campaign
└── Ad Set (one or more)
    └── Ad (one or more)
```

**Campaign** — defines the advertising objective (CONVERSIONS, REACH, LINK_CLICKS, etc.) and the spending limit. The objective is set at campaign creation and cannot be changed afterward.

**Ad Set** — defines the audience (targeting), schedule, budget, bidding strategy, and placement. Budget can be set at the campaign level (Campaign Budget Optimization) or the ad set level. Ad sets belong to exactly one campaign.

**Ad** — defines the creative (image, video, copy, headline, CTA) and links to an ad set. Ads belong to exactly one ad set. The creative is specified as an `AdCreative` object referenced by ID.

**Supporting objects:**
- `AdCreative` — the visual and copy definition. Can be shared across ads.
- `AdImage` / `AdVideo` — media assets uploaded separately, referenced by hash or ID.
- `CustomAudience` — retargeting or lookalike audiences, referenced by ID from the ad set.

**Object IDs** are assigned by Facebook at creation time and must be stored in the AdCode state file. All subsequent reads and updates reference these IDs.

---

## Known Pain Points

**Ad rejection.** Ads are reviewed by Facebook's automated policy enforcement system after creation. Rejection can happen immediately or hours later. Common rejection reasons: prohibited content categories (financial products, health claims, political content), overly broad targeting combined with certain creative, landing page policy violations, and misleading copy. Rejection does not prevent the API call from succeeding — the ad is created in PAUSED state and then rejected asynchronously.

**Policy enforcement is opaque.** Facebook's ad policies are documented but the automated enforcement does not provide deterministic rules. Copy that passes today may fail tomorrow. Appeals exist but are slow.

**Campaign objective immutability.** Objective cannot be changed after campaign creation. A campaign built with the wrong objective must be deleted and recreated. This is a destructive operation with no undo.

**Budget distribution lag.** When using Campaign Budget Optimization, budget reallocation across ad sets can lag. Changes to ad set bids and budgets do not take effect instantly.

**Rate limits.** The Marketing API uses a scoring system (BUC — Business Use Case rate limits) rather than fixed request-per-second limits. Heavy batch operations can exhaust the limit quickly. The SDK surfaces rate limit headers; the apply engine should handle backoff.

**API versioning.** Meta deprecates API versions on a roughly annual schedule. The `facebook-business` SDK version must be kept in sync with the API version in use. Breaking changes between versions are common.

---

## How Pre-Push AI Validation Addresses Rejections

The pre-push validation step (via `validate_campaigns` MCP tool) runs the proposed JSON through an AI policy check before any API call is made. The goal is not to replace Facebook's enforcement — it is to catch likely rejections early so they can be communicated to the client before the campaign is trafficked.

The validator checks for:
- Known prohibited content categories in ad copy and landing page URLs
- Missing required fields that will cause API errors (vs. policy rejections)
- Copy patterns that frequently trigger rejection (superlatives, before/after claims, certain health and financial language)
- Targeting configurations known to trigger Special Ad Category requirements

The validator outputs warnings with severity levels. A warning does not block the push — the operator decides whether to proceed. The intent is to shift the discovery of policy issues from post-rejection (after the campaign is live and the client has been told it's running) to pre-push (before the API is called).

---

## Python SDK Usage

```python
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign

FacebookAdsApi.init(app_id, app_secret, access_token)

account = AdAccount(f'act_{account_id}')

# Create campaign
campaign = account.create_campaign(fields=[], params={
    'name': 'My Campaign',
    'objective': Campaign.Objective.link_clicks,
    'status': Campaign.Status.paused,
    'special_ad_categories': [],
})

campaign_id = campaign['id']
```

The SDK uses lazy loading — fields must be explicitly requested when reading objects. The apply engine should request only the fields it needs to minimize response size and rate limit consumption.

---

## Required Fields for Campaign JSON Schema

This is a working list to be expanded as the schema is formalized.

**Campaign level:**
- `name` (string, required)
- `objective` (enum, required — immutable after creation)
- `status` (enum: ACTIVE | PAUSED, required)
- `special_ad_categories` (array, required — empty array if none apply)
- `spend_cap` (integer, optional — in account currency cents)
- `daily_budget` or `lifetime_budget` (required if CBO enabled)

**Ad Set level:**
- `name` (string, required)
- `campaign_id` (string, required — reference to parent)
- `status` (enum, required)
- `targeting` (object, required — see Targeting spec)
- `billing_event` (enum, required — e.g. IMPRESSIONS, LINK_CLICKS)
- `optimization_goal` (enum, required)
- `bid_amount` (integer, optional — in account currency cents)
- `daily_budget` or `lifetime_budget` (required if not using CBO)
- `start_time` (ISO 8601, required for lifetime budget)
- `end_time` (ISO 8601, required for lifetime budget)

**Ad level:**
- `name` (string, required)
- `adset_id` (string, required — reference to parent)
- `status` (enum, required)
- `creative` (object or creative_id reference, required)

**AdCreative level:**
- `name` (string, required)
- `object_story_spec` (object, required — defines link, image/video, copy, headline, CTA)

---

## References

- [Marketing API Overview](https://developers.facebook.com/docs/marketing-apis)
- [Campaign object reference](https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-group)
- [Ad Set object reference](https://developers.facebook.com/docs/marketing-api/reference/ad-campaign)
- [Ad object reference](https://developers.facebook.com/docs/marketing-api/reference/adgroup)
- [facebook-business Python SDK on GitHub](https://github.com/facebook/facebook-python-business-sdk)
- [Ad Policy overview](https://www.facebook.com/policies/ads/)
