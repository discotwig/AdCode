import argparse
import logging
import os
from dataclasses import dataclass, field
from enum import Enum

from src.api.meta import MetaClient
from src.services.state import StateFile

logger = logging.getLogger(__name__)

_CAMPAIGN_TRACKED = {"name", "status", "objective", "special_ad_categories"}
_ADSET_TRACKED = {"name", "status", "billing_event", "optimization_goal", "daily_budget", "lifetime_budget"}
_AD_TRACKED = {"name", "status"}


class DriftType(str, Enum):
    IN_SYNC = "IN_SYNC"
    MISSING_FROM_FACEBOOK = "MISSING_FROM_FACEBOOK"
    MISSING_FROM_STATE = "MISSING_FROM_STATE"
    FIELD_MISMATCH = "FIELD_MISMATCH"


@dataclass
class DriftItem:
    object_type: str
    name: str
    fb_id: str | None
    drift_type: DriftType
    expected: dict | None = None
    actual: dict | None = None


@dataclass
class DriftReport:
    account_id: str
    items: list[DriftItem] = field(default_factory=list)

    def has_drift(self) -> bool:
        return any(i.drift_type != DriftType.IN_SYNC for i in self.items)

    def drift_items(self) -> list[DriftItem]:
        return [i for i in self.items if i.drift_type != DriftType.IN_SYNC]


def fetch_actuals(account_id: str, client: MetaClient) -> dict:
    campaigns = client.list_campaigns(account_id)
    result: dict[str, dict] = {}
    for campaign in campaigns:
        cid = campaign.get("id", "")
        cname = _fix_mojibake(campaign.get("name", cid))
        adsets_raw = client.list_adsets(cid)
        adsets: dict[str, dict] = {}
        for adset in adsets_raw:
            aid = adset.get("id", "")
            aname = _fix_mojibake(adset.get("name", aid))
            ads_raw = client.list_ads(aid)
            ads: dict[str, dict] = {}
            for ad in ads_raw:
                ad_id = ad.get("id", "")
                ad_name = _fix_mojibake(ad.get("name", ad_id))
                ads[ad_name] = {**ad, "fb_id": ad_id}
            adsets[aname] = {**adset, "fb_id": aid, "ads": ads}
        result[cname] = {**campaign, "fb_id": cid, "ad_sets": adsets}
    return result


def _fix_mojibake(s: str) -> str:
    """Facebook SDK sometimes returns UTF-8 bytes decoded as Latin-1 (e.g. em dash → â€"). Reverse it."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _values_equal(a, b) -> bool:
    if a == b:
        return True
    # Facebook returns numeric fields (budgets, bid amounts) as strings; coerce for comparison.
    try:
        return int(a) == int(b)
    except (TypeError, ValueError):
        return False


def _compare_fields(tracked: set, expected: dict, actual: dict) -> dict:
    mismatches = {}
    for field_name in tracked:
        exp_val = expected.get(field_name)
        act_val = actual.get(field_name)
        if exp_val is not None and not _values_equal(exp_val, act_val):
            mismatches[field_name] = {"expected": exp_val, "actual": act_val}
    return mismatches


def diff_state(state: StateFile, actuals: dict) -> DriftReport:
    report = DriftReport(account_id=state.account_id)
    state_data = state.campaigns()

    # Check campaigns in state against actuals
    for cname, cstate in state_data.items():
        fb_id = cstate.get("fb_id", "")
        params = cstate.get("params", {})

        if cname not in actuals:
            report.items.append(DriftItem(
                object_type="campaign", name=cname, fb_id=fb_id,
                drift_type=DriftType.MISSING_FROM_FACEBOOK,
                expected=params, actual=None,
            ))
            continue

        actual_campaign = actuals[cname]
        mismatches = _compare_fields(_CAMPAIGN_TRACKED, params, actual_campaign)
        if mismatches:
            report.items.append(DriftItem(
                object_type="campaign", name=cname, fb_id=fb_id,
                drift_type=DriftType.FIELD_MISMATCH,
                expected={k: v["expected"] for k, v in mismatches.items()},
                actual={k: v["actual"] for k, v in mismatches.items()},
            ))
        else:
            report.items.append(DriftItem(
                object_type="campaign", name=cname, fb_id=fb_id,
                drift_type=DriftType.IN_SYNC,
            ))

        actual_adsets = actual_campaign.get("ad_sets", {})
        for aname, astate in cstate.get("ad_sets", {}).items():
            afb_id = astate.get("fb_id", "")
            aparams = astate.get("params", {})

            if aname not in actual_adsets:
                report.items.append(DriftItem(
                    object_type="adset", name=aname, fb_id=afb_id,
                    drift_type=DriftType.MISSING_FROM_FACEBOOK,
                    expected=aparams, actual=None,
                ))
                continue

            actual_adset = actual_adsets[aname]
            mismatches = _compare_fields(_ADSET_TRACKED, aparams, actual_adset)
            if mismatches:
                report.items.append(DriftItem(
                    object_type="adset", name=aname, fb_id=afb_id,
                    drift_type=DriftType.FIELD_MISMATCH,
                    expected={k: v["expected"] for k, v in mismatches.items()},
                    actual={k: v["actual"] for k, v in mismatches.items()},
                ))
            else:
                report.items.append(DriftItem(
                    object_type="adset", name=aname, fb_id=afb_id,
                    drift_type=DriftType.IN_SYNC,
                ))

            actual_ads = actual_adset.get("ads", {})
            for ad_name, adstate in astate.get("ads", {}).items():
                ad_fb_id = adstate.get("fb_id", "")
                ad_params = adstate.get("params", {})

                if ad_name not in actual_ads:
                    report.items.append(DriftItem(
                        object_type="ad", name=ad_name, fb_id=ad_fb_id,
                        drift_type=DriftType.MISSING_FROM_FACEBOOK,
                        expected=ad_params, actual=None,
                    ))
                    continue

                actual_ad = actual_ads[ad_name]
                mismatches = _compare_fields(_AD_TRACKED, ad_params, actual_ad)
                if mismatches:
                    report.items.append(DriftItem(
                        object_type="ad", name=ad_name, fb_id=ad_fb_id,
                        drift_type=DriftType.FIELD_MISMATCH,
                        expected={k: v["expected"] for k, v in mismatches.items()},
                        actual={k: v["actual"] for k, v in mismatches.items()},
                    ))
                else:
                    report.items.append(DriftItem(
                        object_type="ad", name=ad_name, fb_id=ad_fb_id,
                        drift_type=DriftType.IN_SYNC,
                    ))

    # Check actuals for objects not in state (created outside AdCode)
    for cname, actual_campaign in actuals.items():
        if cname not in state_data:
            report.items.append(DriftItem(
                object_type="campaign", name=cname, fb_id=actual_campaign.get("fb_id"),
                drift_type=DriftType.MISSING_FROM_STATE,
                expected=None, actual=actual_campaign,
            ))
            continue

        state_adsets = state_data[cname].get("ad_sets", {})
        for aname, actual_adset in actual_campaign.get("ad_sets", {}).items():
            if aname not in state_adsets:
                report.items.append(DriftItem(
                    object_type="adset", name=aname, fb_id=actual_adset.get("fb_id"),
                    drift_type=DriftType.MISSING_FROM_STATE,
                    expected=None, actual=actual_adset,
                ))
                continue

            state_ads = state_adsets[aname].get("ads", {})
            for ad_name, actual_ad in actual_adset.get("ads", {}).items():
                if ad_name not in state_ads:
                    report.items.append(DriftItem(
                        object_type="ad", name=ad_name, fb_id=actual_ad.get("fb_id"),
                        drift_type=DriftType.MISSING_FROM_STATE,
                        expected=None, actual=actual_ad,
                    ))

    return report


def format_report(drift_report: DriftReport) -> str:
    if not drift_report.has_drift():
        return f"Account {drift_report.account_id}: all objects in sync. No drift detected."

    lines = [f"Drift report — account {drift_report.account_id}", ""]
    for item in drift_report.drift_items():
        if item.drift_type == DriftType.IN_SYNC:
            continue
        lines.append(f"[{item.drift_type}] {item.object_type.upper()}: {item.name}  (fb_id: {item.fb_id})")
        if item.drift_type == DriftType.FIELD_MISMATCH:
            for fname in (item.expected or {}):
                exp = (item.expected or {}).get(fname)
                act = (item.actual or {}).get(fname)
                lines.append(f"    {fname}: expected={exp!r}  actual={act!r}")
        elif item.drift_type == DriftType.MISSING_FROM_FACEBOOK:
            lines.append("    Object is in state file but not found in Facebook.")
        elif item.drift_type == DriftType.MISSING_FROM_STATE:
            lines.append("    Object exists in Facebook but is not tracked in state file.")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Detect drift between state file and Facebook actuals.")
    parser.add_argument("account_id", help="Facebook ad account ID (act_XXXXXXXXX or plain digits)")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    account_id = args.account_id if args.account_id.startswith("act_") else f"act_{args.account_id}"

    meta = MetaClient(
        app_id=os.environ["FB_APP_ID"],
        app_secret=os.environ["FB_APP_SECRET"],
        access_token=os.environ["FB_ACCESS_TOKEN"],
        account_id=account_id,
    )
    state = StateFile.load(account_id)
    actuals = fetch_actuals(account_id, meta)
    report = diff_state(state, actuals)
    print(format_report(report))

    if report.has_drift():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
