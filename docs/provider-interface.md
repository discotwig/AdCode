# Provider Interface

Meta is the only implemented provider today. This document describes the provider boundary AdCode should move toward before adding another platform.

## Goal

The core engine should own desired-state planning, state updates, delete guards, and drift concepts. Provider clients should own API-specific object creation, updates, deletion, listing, and normalization.

## Current Provider

`src/api/meta.py` wraps the Facebook Business SDK and exposes methods for:

- campaigns;
- ad sets;
- ads;
- creatives;
- hierarchy listing;
- basic retry handling.

The rest of the code should avoid direct Facebook SDK usage.

## Minimum Provider Capability

A provider should support these operations or explicitly mark them unsupported:

```text
list_campaigns(account_id)
list_adsets(campaign_id)
list_ads(adset_id)

create_campaign(params)
update_campaign(id, params)
delete_campaign(id)

create_adset(campaign_id, params)
update_adset(id, params)
delete_adset(id)

create_ad(adset_id, params)
update_ad(id, params)
delete_ad(id)
```

Some providers may not have a separate creative object. The provider should normalize that difference behind its API rather than leaking it into the plan engine.

## Normalized Concepts

The engine currently assumes this hierarchy:

```text
account
  campaign
    ad set
      ad
        creative
```

A second provider may use different names, but it should map to equivalent concepts where possible. If a platform has a materially different hierarchy, the schema and plan engine should make that explicit rather than forcing an inaccurate mapping.

## Drift Requirements

Providers must return enough live data for drift detection:

- stable IDs;
- names;
- status/effective status where available;
- budget fields;
- targeting fields;
- optimization/bidding fields;
- parent-child relationships.

Provider responses should be converted into plain Python dictionaries before reaching reconciliation code.

## Safety Requirements

Provider implementations must preserve:

- no API calls during planning except live reads explicitly needed for drift/import workflows;
- explicit delete methods;
- clear errors when provider APIs reject a change;
- retry behavior only for known transient or rate-limit errors;
- no silent fallback from update to create.

## Open Questions

- Should provider schemas be separate files or one provider-tagged schema?
- Should the plan operation dataclasses become provider-neutral?
- How should provider-specific fields be preserved without weakening schema validation?
- What is the smallest useful Google Ads subset for a second provider proof?
