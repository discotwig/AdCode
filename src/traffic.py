import argparse
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema

from src.api.meta import MetaClient
from src.services.state import StateFile

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "campaign.schema.json"

with open(SCHEMA_PATH) as _f:
    _CAMPAIGN_SCHEMA = json.load(_f)

# Fields compared when diffing state vs desired to decide create vs update
_CAMPAIGN_DIFF_FIELDS = {"name", "objective", "status", "special_ad_categories", "spend_cap", "daily_budget"}
_ADSET_DIFF_FIELDS = {"name", "status", "billing_event", "optimization_goal",
                      "bid_amount", "bid_strategy", "daily_budget", "lifetime_budget", "start_time", "end_time"}
_AD_DIFF_FIELDS = {"name", "status"}


# ------------------------------------------------------------------
# Operation types
# ------------------------------------------------------------------

@dataclass
class CreateCampaign:
    campaign: dict

@dataclass
class UpdateCampaign:
    campaign_name: str
    fb_id: str
    changed_fields: dict
    old_campaign_name: str | None = None

@dataclass
class CreateAdSet:
    campaign_name: str
    adset: dict

@dataclass
class UpdateAdSet:
    campaign_name: str
    adset_name: str
    fb_id: str
    changed_fields: dict
    old_campaign_name: str | None = None
    old_adset_name: str | None = None

@dataclass
class CreateAd:
    campaign_name: str
    adset_name: str
    ad: dict

@dataclass
class UpdateAd:
    campaign_name: str
    adset_name: str
    ad_name: str
    fb_id: str
    changed_fields: dict
    old_campaign_name: str | None = None
    old_adset_name: str | None = None
    old_ad_name: str | None = None

@dataclass
class DeleteCampaign:
    campaign_name: str
    fb_id: str

@dataclass
class DeleteAdSet:
    campaign_name: str
    adset_name: str
    fb_id: str

@dataclass
class DeleteAd:
    campaign_name: str
    adset_name: str
    ad_name: str
    fb_id: str


@dataclass
class Plan:
    operations: list = field(default_factory=list)

    def __len__(self):
        return len(self.operations)

    @property
    def has_deletes(self) -> bool:
        return any(isinstance(op, (DeleteCampaign, DeleteAdSet, DeleteAd)) for op in self.operations)

    def summary(self) -> str:
        counts: dict[str, int] = {}
        for op in self.operations:
            key = type(op).__name__
            counts[key] = counts.get(key, 0) + 1
        if not counts:
            return "No changes."
        return ", ".join(f"{v} {k}" for k, v in counts.items())


@dataclass
class OperationResult:
    operation: object
    success: bool
    error: str | None = None


@dataclass
class ApplyResult:
    succeeded: list[OperationResult] = field(default_factory=list)
    failed: list[OperationResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.failed) == 0

    def summary(self) -> str:
        lines = [f"{len(self.succeeded)} succeeded, {len(self.failed)} failed."]
        for r in self.failed:
            lines.append(f"  FAILED {type(r.operation).__name__}: {r.error}")
        return "\n".join(lines)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _diff_fields(desired: dict, stored: dict, fields: set) -> dict:
    return {k: desired[k] for k in fields if k in desired and desired.get(k) != stored.get(k)}


def _campaign_api_params(campaign: dict) -> dict:
    keys = {"name", "objective", "status", "special_ad_categories", "spend_cap", "daily_budget"}
    return {k: v for k, v in campaign.items() if k in keys}


def _adset_api_params(adset: dict) -> dict:
    keys = {"name", "status", "targeting", "billing_event", "optimization_goal",
            "bid_amount", "bid_strategy", "daily_budget", "lifetime_budget", "start_time", "end_time"}
    return {k: v for k, v in adset.items() if k in keys}


def _creative_api_params(creative: dict, page_id_override: str | None = None) -> dict:
    return {k: v for k, v in creative.items()}


# ------------------------------------------------------------------
# Core functions
# ------------------------------------------------------------------

def load_campaign_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    jsonschema.validate(data, _CAMPAIGN_SCHEMA)
    return data


def plan(campaign_json: dict, state: StateFile, client: MetaClient) -> Plan:
    create_update_ops: list = []
    delete_ad_ops: list = []
    delete_adset_ops: list = []
    delete_campaign_ops: list = []

    desired_campaigns = {c["name"]: c for c in campaign_json["campaigns"]}
    desired_campaign_fb_ids = {c["fb_id"] for c in campaign_json["campaigns"] if c.get("fb_id")}

    for campaign in campaign_json["campaigns"]:
        cname = campaign["name"]
        campaign_fb_id = campaign.get("fb_id")
        state_campaign_name = cname
        if campaign_fb_id:
            campaign_match = state.get_campaign_by_fb_id(campaign_fb_id)
            if campaign_match:
                state_campaign_name, state_campaign = campaign_match
                existing_campaign_id = campaign_fb_id
                stored_params = state_campaign.get("params", {})
            else:
                existing_campaign_id = None
                stored_params = {}
        else:
            existing_campaign_id = state.get_campaign_id(cname)
            stored_params = state.get_campaign_params(cname) or {}

        if existing_campaign_id is None:
            create_update_ops.append(CreateCampaign(campaign=campaign))
        else:
            changed = _diff_fields(campaign, stored_params, _CAMPAIGN_DIFF_FIELDS)
            if changed:
                create_update_ops.append(UpdateCampaign(
                    campaign_name=cname,
                    fb_id=existing_campaign_id,
                    changed_fields=changed,
                    old_campaign_name=state_campaign_name if state_campaign_name != cname else None,
                ))

        desired_adsets = {a["name"]: a for a in campaign.get("ad_sets", [])}
        desired_adset_fb_ids = {a["fb_id"] for a in campaign.get("ad_sets", []) if a.get("fb_id")}

        for adset in campaign.get("ad_sets", []):
            aname = adset["name"]
            adset_fb_id = adset.get("fb_id")
            state_adset_name = aname
            state_campaign_for_adset = state_campaign_name
            if adset_fb_id:
                adset_match = state.get_adset_by_fb_id(adset_fb_id)
                if adset_match:
                    state_campaign_for_adset, state_adset_name, state_adset = adset_match
                    existing_adset_id = adset_fb_id
                    stored_adset_params = state_adset.get("params", {})
                else:
                    existing_adset_id = None
                    stored_adset_params = {}
            else:
                existing_adset_id = state.get_adset_id(state_campaign_name, aname)
                stored_adset_params = state.get_adset_params(state_campaign_name, aname) or {}

            if existing_adset_id is None:
                create_update_ops.append(CreateAdSet(campaign_name=cname, adset=adset))
            else:
                changed = _diff_fields(adset, stored_adset_params, _ADSET_DIFF_FIELDS)
                if changed:
                    create_update_ops.append(UpdateAdSet(
                        campaign_name=cname,
                        adset_name=aname,
                        fb_id=existing_adset_id,
                        changed_fields=changed,
                        old_campaign_name=state_campaign_for_adset if state_campaign_for_adset != cname else None,
                        old_adset_name=state_adset_name if state_adset_name != aname else None,
                    ))

            desired_ads = {a["name"]: a for a in adset.get("ads", [])}
            desired_ad_fb_ids = {a["fb_id"] for a in adset.get("ads", []) if a.get("fb_id")}

            for ad in adset.get("ads", []):
                adname = ad["name"]
                ad_fb_id = ad.get("fb_id")
                state_ad_name = adname
                state_campaign_for_ad = state_campaign_for_adset
                state_adset_for_ad = state_adset_name
                if ad_fb_id:
                    ad_match = state.get_ad_by_fb_id(ad_fb_id)
                    if ad_match:
                        state_campaign_for_ad, state_adset_for_ad, state_ad_name, state_ad = ad_match
                        existing_ad_id = ad_fb_id
                        stored_ad_params = state_ad.get("params", {})
                    else:
                        existing_ad_id = None
                        stored_ad_params = {}
                else:
                    existing_ad_id = state.get_ad_id(state_campaign_for_adset, state_adset_name, adname)
                    stored_ad_params = state.get_ad_params(state_campaign_for_adset, state_adset_name, adname) or {}

                if existing_ad_id is None:
                    create_update_ops.append(CreateAd(campaign_name=cname, adset_name=aname, ad=ad))
                else:
                    changed = _diff_fields(ad, stored_ad_params, _AD_DIFF_FIELDS)
                    if changed:
                        create_update_ops.append(UpdateAd(
                            campaign_name=cname,
                            adset_name=aname,
                            ad_name=adname,
                            fb_id=existing_ad_id,
                            changed_fields=changed,
                            old_campaign_name=state_campaign_for_ad if state_campaign_for_ad != cname else None,
                            old_adset_name=state_adset_for_ad if state_adset_for_ad != aname else None,
                            old_ad_name=state_ad_name if state_ad_name != adname else None,
                        ))

            # Ads removed from this adset
            state_ads = (state.campaigns().get(state_campaign_for_adset, {})
                         .get("ad_sets", {}).get(state_adset_name, {}).get("ads", {}))
            for ad_name, adstate in state_ads.items():
                ad_fb_id = adstate.get("fb_id")
                if ad_name not in desired_ads and ad_fb_id not in desired_ad_fb_ids:
                    delete_ad_ops.append(DeleteAd(
                        campaign_name=state_campaign_for_adset, adset_name=state_adset_name, ad_name=ad_name,
                        fb_id=adstate["fb_id"],
                    ))

        # Adsets removed from this campaign
        state_adsets = state.campaigns().get(state_campaign_name, {}).get("ad_sets", {})
        for aname, astate in state_adsets.items():
            adset_fb_id = astate.get("fb_id")
            if aname not in desired_adsets and adset_fb_id not in desired_adset_fb_ids:
                for ad_name, adstate in astate.get("ads", {}).items():
                    delete_ad_ops.append(DeleteAd(
                        campaign_name=state_campaign_name, adset_name=aname, ad_name=ad_name,
                        fb_id=adstate["fb_id"],
                    ))
                delete_adset_ops.append(DeleteAdSet(
                    campaign_name=state_campaign_name, adset_name=aname, fb_id=astate["fb_id"],
                ))

    # Campaigns removed from JSON entirely
    for cname, cstate in state.campaigns().items():
        campaign_fb_id = cstate.get("fb_id")
        if cname not in desired_campaigns and campaign_fb_id not in desired_campaign_fb_ids:
            for aname, astate in cstate.get("ad_sets", {}).items():
                for ad_name, adstate in astate.get("ads", {}).items():
                    delete_ad_ops.append(DeleteAd(
                        campaign_name=cname, adset_name=aname, ad_name=ad_name,
                        fb_id=adstate["fb_id"],
                    ))
                delete_adset_ops.append(DeleteAdSet(
                    campaign_name=cname, adset_name=aname, fb_id=astate["fb_id"],
                ))
            delete_campaign_ops.append(DeleteCampaign(
                campaign_name=cname, fb_id=cstate["fb_id"],
            ))

    return Plan(operations=create_update_ops + delete_ad_ops + delete_adset_ops + delete_campaign_ops)


def _persist_created_fb_ids(
    campaign_json: dict | None,
    campaign_json_path: str | None,
    created_campaign_ids: dict[str, str],
    created_adset_ids: dict[tuple[str, str], str],
    created_ad_ids: dict[tuple[str, str, str], str],
) -> None:
    if not campaign_json or not campaign_json_path:
        return

    changed = False
    for campaign in campaign_json.get("campaigns", []):
        cname = campaign["name"]
        campaign_fb_id = created_campaign_ids.get(cname)
        if campaign_fb_id and not campaign.get("fb_id"):
            campaign["fb_id"] = campaign_fb_id
            changed = True

        for adset in campaign.get("ad_sets", []):
            aname = adset["name"]
            adset_fb_id = created_adset_ids.get((cname, aname))
            if adset_fb_id and not adset.get("fb_id"):
                adset["fb_id"] = adset_fb_id
                changed = True

            for ad in adset.get("ads", []):
                adname = ad["name"]
                ad_fb_id = created_ad_ids.get((cname, aname, adname))
                if ad_fb_id and not ad.get("fb_id"):
                    ad["fb_id"] = ad_fb_id
                    changed = True

    if changed:
        with open(campaign_json_path, "w", encoding="utf-8") as f:
            json.dump(campaign_json, f, indent=2, ensure_ascii=False)


def apply(
    p: Plan,
    client: MetaClient,
    state: StateFile,
    campaign_json: dict | None = None,
    campaign_json_path: str | None = None,
) -> ApplyResult:
    result = ApplyResult()

    # Maps campaign/adset names to their FB IDs for newly created objects within this apply run
    new_campaign_ids: dict[str, str] = {}
    new_adset_ids: dict[tuple, str] = {}
    new_ad_ids: dict[tuple, str] = {}

    for op in p.operations:
        try:
            if isinstance(op, CreateCampaign):
                campaign = op.campaign
                cname = campaign["name"]
                fb_id = client.create_campaign(_campaign_api_params(campaign))
                state.upsert_campaign(cname, fb_id, _campaign_api_params(campaign))
                state.save()
                new_campaign_ids[cname] = fb_id
                result.succeeded.append(OperationResult(op, success=True))

            elif isinstance(op, UpdateCampaign):
                client.update_campaign(op.fb_id, op.changed_fields)
                lookup_campaign_name = op.old_campaign_name or op.campaign_name
                stored = state.get_campaign_params(lookup_campaign_name) or {}
                state.upsert_campaign(
                    op.campaign_name,
                    op.fb_id,
                    {**stored, **op.changed_fields},
                    old_name=op.old_campaign_name,
                )
                state.save()
                result.succeeded.append(OperationResult(op, success=True))

            elif isinstance(op, CreateAdSet):
                cname = op.campaign_name
                campaign_id = new_campaign_ids.get(cname) or state.get_campaign_id(cname)
                fb_id = client.create_adset(campaign_id, _adset_api_params(op.adset))
                state.upsert_adset(cname, op.adset["name"], fb_id, _adset_api_params(op.adset))
                state.save()
                new_adset_ids[(cname, op.adset["name"])] = fb_id
                result.succeeded.append(OperationResult(op, success=True))

            elif isinstance(op, UpdateAdSet):
                client.update_adset(op.fb_id, op.changed_fields)
                lookup_campaign_name = op.old_campaign_name or op.campaign_name
                lookup_adset_name = op.old_adset_name or op.adset_name
                stored = state.get_adset_params(lookup_campaign_name, lookup_adset_name) or {}
                state.upsert_adset(
                    op.campaign_name,
                    op.adset_name,
                    op.fb_id,
                    {**stored, **op.changed_fields},
                    old_campaign_name=op.old_campaign_name,
                    old_adset_name=op.old_adset_name,
                )
                state.save()
                result.succeeded.append(OperationResult(op, success=True))

            elif isinstance(op, CreateAd):
                cname = op.campaign_name
                aname = op.adset_name
                adset_id = new_adset_ids.get((cname, aname)) or state.get_adset_id(cname, aname)
                creative = op.ad["creative"]
                creative_id = client.create_creative({
                    "name": creative["name"],
                    "object_story_spec": creative["object_story_spec"],
                })
                ad_params = {"name": op.ad["name"], "status": op.ad["status"], "creative": {"creative_id": creative_id}}
                fb_id = client.create_ad(adset_id, ad_params)
                state.upsert_ad(cname, aname, op.ad["name"], fb_id, creative_id, {"name": op.ad["name"], "status": op.ad["status"]})
                state.save()
                new_ad_ids[(cname, aname, op.ad["name"])] = fb_id
                result.succeeded.append(OperationResult(op, success=True))

            elif isinstance(op, UpdateAd):
                client.update_ad(op.fb_id, op.changed_fields)
                lookup_campaign_name = op.old_campaign_name or op.campaign_name
                lookup_adset_name = op.old_adset_name or op.adset_name
                lookup_ad_name = op.old_ad_name or op.ad_name
                stored = state.get_ad_params(lookup_campaign_name, lookup_adset_name, lookup_ad_name) or {}
                creative_id = (
                    state.to_dict()["campaigns"][lookup_campaign_name]["ad_sets"][lookup_adset_name]["ads"][lookup_ad_name]["creative_id"]
                )
                state.upsert_ad(
                    op.campaign_name,
                    op.adset_name,
                    op.ad_name,
                    op.fb_id,
                    creative_id,
                    {**stored, **op.changed_fields},
                    old_campaign_name=op.old_campaign_name,
                    old_adset_name=op.old_adset_name,
                    old_ad_name=op.old_ad_name,
                )
                state.save()
                result.succeeded.append(OperationResult(op, success=True))

            elif isinstance(op, DeleteAd):
                client.delete_ad(op.fb_id)
                state.delete_ad(op.campaign_name, op.adset_name, op.ad_name)
                state.save()
                result.succeeded.append(OperationResult(op, success=True))

            elif isinstance(op, DeleteAdSet):
                client.delete_adset(op.fb_id)
                state.delete_adset(op.campaign_name, op.adset_name)
                state.save()
                result.succeeded.append(OperationResult(op, success=True))

            elif isinstance(op, DeleteCampaign):
                client.delete_campaign(op.fb_id)
                state.delete_campaign(op.campaign_name)
                state.save()
                result.succeeded.append(OperationResult(op, success=True))

        except Exception as e:
            logger.error("operation failed: %s — %s", type(op).__name__, e)
            result.failed.append(OperationResult(op, success=False, error=str(e)))

    _persist_created_fb_ids(
        campaign_json=campaign_json,
        campaign_json_path=campaign_json_path,
        created_campaign_ids=new_campaign_ids,
        created_adset_ids=new_adset_ids,
        created_ad_ids=new_ad_ids,
    )

    return result


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Apply campaign JSON to Facebook.")
    parser.add_argument("campaign_file", help="Path to campaign JSON file")
    parser.add_argument("--dry-run", action="store_true", help="Plan only; do not call the API")
    args = parser.parse_args()

    import os
    from dotenv import load_dotenv
    load_dotenv()

    campaign_json = load_campaign_json(args.campaign_file)
    account_id = campaign_json["account_id"]

    meta = MetaClient(
        app_id=os.environ["FB_APP_ID"],
        app_secret=os.environ["FB_APP_SECRET"],
        access_token=os.environ["FB_ACCESS_TOKEN"],
        account_id=account_id,
    )
    state = StateFile.load(account_id)
    p = plan(campaign_json, state, meta)

    print(f"Plan: {p.summary()}")
    for op in p.operations:
        print(f"  {type(op).__name__}: {getattr(op, 'campaign_name', '') or getattr(op, 'campaign', {}).get('name', '')}")

    if args.dry_run:
        return

    result = apply(p, meta, state, campaign_json=campaign_json, campaign_json_path=args.campaign_file)
    print(result.summary())
    if not result.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
