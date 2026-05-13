import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Default fallback used by tests (patched via patch("src.services.state.STATE_DIR", tmp_path)).
# In normal operation, every StateFile is constructed with an explicit state_dir derived
# from the template path — this fallback is never reached in production.
STATE_DIR = Path(__file__).parent.parent.parent / "state"


class StateFile:
    def __init__(
        self,
        account_id: str,
        data: dict | None = None,
        state_dir: Path | None = None,
        stack_name: str | None = None,
    ):
        self.account_id = account_id
        # stack_name drives the filename; falls back to account_id for backwards compatibility.
        self.stack_name: str = stack_name if stack_name is not None else account_id
        self._data: dict = data or {"account_id": account_id, "last_pushed_at": "", "campaigns": {}}
        self._state_dir: Path | None = state_dir  # None → fall through to STATE_DIR at call time

    @classmethod
    def load(
        cls,
        account_id: str,
        stack_name: str | None = None,
        state_dir: Path | None = None,
    ) -> "StateFile":
        _dir = state_dir if state_dir is not None else STATE_DIR
        _name = stack_name if stack_name is not None else account_id
        path = _dir / f"{_name}.json"
        if not path.exists():
            return cls(account_id, state_dir=state_dir, stack_name=stack_name)
        with open(path, encoding="utf-8") as f:
            return cls(account_id, json.load(f), state_dir=state_dir, stack_name=stack_name)

    def save(self) -> None:
        # Resolve at call time so test patches of STATE_DIR still work when state_dir is None.
        _dir = self._state_dir if self._state_dir is not None else STATE_DIR
        _dir.mkdir(parents=True, exist_ok=True)
        self._data["last_pushed_at"] = datetime.now(timezone.utc).isoformat()
        path = _dir / f"{self.stack_name}.json"
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp_path, path)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_campaign_id(self, campaign_name: str) -> str | None:
        return self._data["campaigns"].get(campaign_name, {}).get("fb_id")

    def get_campaign_by_fb_id(self, fb_id: str) -> tuple[str, dict] | None:
        for campaign_name, campaign in self._data["campaigns"].items():
            if campaign.get("fb_id") == fb_id:
                return campaign_name, campaign
        return None

    def get_adset_id(self, campaign_name: str, adset_name: str) -> str | None:
        campaign = self._data["campaigns"].get(campaign_name, {})
        return campaign.get("ad_sets", {}).get(adset_name, {}).get("fb_id")

    def get_adset_by_fb_id(self, fb_id: str) -> tuple[str, str, dict] | None:
        for campaign_name, campaign in self._data["campaigns"].items():
            for adset_name, adset in campaign.get("ad_sets", {}).items():
                if adset.get("fb_id") == fb_id:
                    return campaign_name, adset_name, adset
        return None

    def get_ad_id(self, campaign_name: str, adset_name: str, ad_name: str) -> str | None:
        campaign = self._data["campaigns"].get(campaign_name, {})
        adset = campaign.get("ad_sets", {}).get(adset_name, {})
        return adset.get("ads", {}).get(ad_name, {}).get("fb_id")

    def get_ad_by_fb_id(self, fb_id: str) -> tuple[str, str, str, dict] | None:
        for campaign_name, campaign in self._data["campaigns"].items():
            for adset_name, adset in campaign.get("ad_sets", {}).items():
                for ad_name, ad in adset.get("ads", {}).items():
                    if ad.get("fb_id") == fb_id:
                        return campaign_name, adset_name, ad_name, ad
        return None

    def get_campaign_params(self, campaign_name: str) -> dict | None:
        return self._data["campaigns"].get(campaign_name, {}).get("params")

    def get_adset_params(self, campaign_name: str, adset_name: str) -> dict | None:
        campaign = self._data["campaigns"].get(campaign_name, {})
        return campaign.get("ad_sets", {}).get(adset_name, {}).get("params")

    def get_ad_params(self, campaign_name: str, adset_name: str, ad_name: str) -> dict | None:
        campaign = self._data["campaigns"].get(campaign_name, {})
        adset = campaign.get("ad_sets", {}).get(adset_name, {})
        return adset.get("ads", {}).get(ad_name, {}).get("params")

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert_campaign(self, campaign_name: str, fb_id: str, params: dict, old_name: str | None = None) -> None:
        if old_name and old_name != campaign_name:
            old_campaign = self._data["campaigns"].pop(old_name, {})
        else:
            old_campaign = {}
        existing = self._data["campaigns"].get(campaign_name, {})
        self._data["campaigns"][campaign_name] = {
            "fb_id": fb_id,
            "params": params,
            "ad_sets": existing.get("ad_sets", old_campaign.get("ad_sets", {})),
        }

    def upsert_adset(
        self,
        campaign_name: str,
        adset_name: str,
        fb_id: str,
        params: dict,
        old_campaign_name: str | None = None,
        old_adset_name: str | None = None,
    ) -> None:
        if campaign_name in self._data["campaigns"]:
            campaign_lookup_name = campaign_name
        elif old_campaign_name and old_campaign_name in self._data["campaigns"]:
            campaign_lookup_name = old_campaign_name
        else:
            campaign_lookup_name = campaign_name
        campaign = self._data["campaigns"].setdefault(campaign_lookup_name, {"fb_id": "", "params": {}, "ad_sets": {}})
        if old_adset_name and old_adset_name != adset_name:
            old_adset = campaign["ad_sets"].pop(old_adset_name, {})
        else:
            old_adset = {}
        existing = campaign["ad_sets"].get(adset_name, {})
        campaign["ad_sets"][adset_name] = {
            "fb_id": fb_id,
            "params": params,
            "ads": existing.get("ads", old_adset.get("ads", {})),
        }

    def upsert_ad(
        self,
        campaign_name: str,
        adset_name: str,
        ad_name: str,
        fb_id: str,
        creative_id: str,
        params: dict,
        old_campaign_name: str | None = None,
        old_adset_name: str | None = None,
        old_ad_name: str | None = None,
    ) -> None:
        if campaign_name in self._data["campaigns"]:
            campaign_lookup_name = campaign_name
        elif old_campaign_name and old_campaign_name in self._data["campaigns"]:
            campaign_lookup_name = old_campaign_name
        else:
            campaign_lookup_name = campaign_name
        campaign = self._data["campaigns"].setdefault(campaign_lookup_name, {"fb_id": "", "params": {}, "ad_sets": {}})
        if adset_name in campaign["ad_sets"]:
            adset_lookup_name = adset_name
        elif old_adset_name and old_adset_name in campaign["ad_sets"]:
            adset_lookup_name = old_adset_name
        else:
            adset_lookup_name = adset_name
        adset = campaign["ad_sets"].setdefault(adset_lookup_name, {"fb_id": "", "params": {}, "ads": {}})
        if old_ad_name and old_ad_name != ad_name:
            old_ad = adset["ads"].pop(old_ad_name, {})
        else:
            old_ad = {}
        existing = adset["ads"].get(ad_name, {})
        adset["ads"][ad_name] = {
            "fb_id": fb_id,
            "creative_id": creative_id,
            "params": params or existing.get("params", old_ad.get("params", {})),
        }

    def delete_campaign(self, campaign_name: str) -> None:
        self._data["campaigns"].pop(campaign_name, None)

    def delete_adset(self, campaign_name: str, adset_name: str) -> None:
        campaign = self._data["campaigns"].get(campaign_name, {})
        campaign.get("ad_sets", {}).pop(adset_name, None)

    def delete_ad(self, campaign_name: str, adset_name: str, ad_name: str) -> None:
        campaign = self._data["campaigns"].get(campaign_name, {})
        adset = campaign.get("ad_sets", {}).get(adset_name, {})
        adset.get("ads", {}).pop(ad_name, None)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return dict(self._data)

    def campaigns(self) -> dict:
        return self._data["campaigns"]
