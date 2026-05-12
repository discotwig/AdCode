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

    for campaign in campaign_json["campaigns"]:
        cname = campaign["name"]
        existing_campaign_id = state.get_campaign_id(cname)

        if existing_campaign_id is None:
            create_update_ops.append(CreateCampaign(campaign=campaign))
        else:
            stored_params = state.get_campaign_params(cname) or {}
            changed = _diff_fields(campaign, stored_params, _CAMPAIGN_DIFF_FIELDS)
            if changed:
                create_update_ops.append(UpdateCampaign(campaign_name=cname, fb_id=existing_campaign_id, changed_fields=changed))

        desired_adsets = {a["name"]: a for a in campaign.get("ad_sets", [])}

        for adset in campaign.get("ad_sets", []):
            aname = adset["name"]
            existing_adset_id = state.get_adset_id(cname, aname)

            if existing_adset_id is None:
                create_update_ops.append(CreateAdSet(campaign_name=cname, adset=adset))
            else:
                stored_adset_params = state.get_adset_params(cname, aname) or {}
                changed = _diff_fields(adset, stored_adset_params, _ADSET_DIFF_FIELDS)
                if changed:
                    create_update_ops.append(UpdateAdSet(campaign_name=cname, adset_name=aname,
                                                         fb_id=existing_adset_id, changed_fields=changed))

            desired_ads = {a["name"]: a for a in adset.get("ads", [])}

            for ad in adset.get("ads", []):
                adname = ad["name"]
                existing_ad_id = state.get_ad_id(cname, aname, adname)

                if existing_ad_id is None:
                    create_update_ops.append(CreateAd(campaign_name=cname, adset_name=aname, ad=ad))
                else:
                    stored_ad_params = state.get_ad_params(cname, aname, adname) or {}
                    changed = _diff_fields(ad, stored_ad_params, _AD_DIFF_FIELDS)
                    if changed:
                        create_update_ops.append(UpdateAd(campaign_name=cname, adset_name=aname, ad_name=adname,
                                                          fb_id=existing_ad_id, changed_fields=changed))

            # Ads removed from this adset
            state_ads = (state.campaigns().get(cname, {})
                         .get("ad_sets", {}).get(aname, {}).get("ads", {}))
            for ad_name, adstate in state_ads.items():
                if ad_name not in desired_ads:
                    delete_ad_ops.append(DeleteAd(
                        campaign_name=cname, adset_name=aname, ad_name=ad_name,
                        fb_id=adstate["fb_id"],
                    ))

        # Adsets removed from this campaign
        state_adsets = state.campaigns().get(cname, {}).get("ad_sets", {})
        for aname, astate in state_adsets.items():
            if aname not in desired_adsets:
                for ad_name, adstate in astate.get("ads", {}).items():
                    delete_ad_ops.append(DeleteAd(
                        campaign_name=cname, adset_name=aname, ad_name=ad_name,
                        fb_id=adstate["fb_id"],
                    ))
                delete_adset_ops.append(DeleteAdSet(
                    campaign_name=cname, adset_name=aname, fb_id=astate["fb_id"],
                ))

    # Campaigns removed from JSON entirely
    for cname, cstate in state.campaigns().items():
        if cname not in desired_campaigns:
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


def apply(p: Plan, client: MetaClient, state: StateFile) -> ApplyResult:
    result = ApplyResult()

    # Maps campaign/adset names to their FB IDs for newly created objects within this apply run
    new_campaign_ids: dict[str, str] = {}
    new_adset_ids: dict[tuple, str] = {}

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
                stored = state.get_campaign_params(op.campaign_name) or {}
                state.upsert_campaign(op.campaign_name, op.fb_id, {**stored, **op.changed_fields})
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
                stored = state.get_adset_params(op.campaign_name, op.adset_name) or {}
                state.upsert_adset(op.campaign_name, op.adset_name, op.fb_id, {**stored, **op.changed_fields})
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
                result.succeeded.append(OperationResult(op, success=True))

            elif isinstance(op, UpdateAd):
                client.update_ad(op.fb_id, op.changed_fields)
                stored = state.get_ad_params(op.campaign_name, op.adset_name, op.ad_name) or {}
                creative_id = state.to_dict()["campaigns"][op.campaign_name]["ad_sets"][op.adset_name]["ads"][op.ad_name]["creative_id"]
                state.upsert_ad(op.campaign_name, op.adset_name, op.ad_name, op.fb_id, creative_id, {**stored, **op.changed_fields})
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

    result = apply(p, meta, state)
    print(result.summary())
    if not result.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
