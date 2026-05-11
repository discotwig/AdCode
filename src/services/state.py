import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(__file__).parent.parent.parent / "state"


class StateFile:
    def __init__(self, account_id: str, data: dict | None = None):
        self.account_id = account_id
        self._data: dict = data or {"account_id": account_id, "last_pushed_at": "", "campaigns": {}}

    @classmethod
    def load(cls, account_id: str) -> "StateFile":
        path = STATE_DIR / f"{account_id}.json"
        if not path.exists():
            return cls(account_id)
        with open(path) as f:
            return cls(account_id, json.load(f))

    def save(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._data["last_pushed_at"] = datetime.now(timezone.utc).isoformat()
        path = STATE_DIR / f"{self.account_id}.json"
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp_path, path)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_campaign_id(self, campaign_name: str) -> str | None:
        return self._data["campaigns"].get(campaign_name, {}).get("fb_id")

    def get_adset_id(self, campaign_name: str, adset_name: str) -> str | None:
        campaign = self._data["campaigns"].get(campaign_name, {})
        return campaign.get("ad_sets", {}).get(adset_name, {}).get("fb_id")

    def get_ad_id(self, campaign_name: str, adset_name: str, ad_name: str) -> str | None:
        campaign = self._data["campaigns"].get(campaign_name, {})
        adset = campaign.get("ad_sets", {}).get(adset_name, {})
        return adset.get("ads", {}).get(ad_name, {}).get("fb_id")

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

    def upsert_campaign(self, campaign_name: str, fb_id: str, params: dict) -> None:
        existing = self._data["campaigns"].get(campaign_name, {})
        self._data["campaigns"][campaign_name] = {
            "fb_id": fb_id,
            "params": params,
            "ad_sets": existing.get("ad_sets", {}),
        }

    def upsert_adset(self, campaign_name: str, adset_name: str, fb_id: str, params: dict) -> None:
        campaign = self._data["campaigns"].setdefault(campaign_name, {"fb_id": "", "params": {}, "ad_sets": {}})
        existing = campaign["ad_sets"].get(adset_name, {})
        campaign["ad_sets"][adset_name] = {
            "fb_id": fb_id,
            "params": params,
            "ads": existing.get("ads", {}),
        }

    def upsert_ad(self, campaign_name: str, adset_name: str, ad_name: str,
                  fb_id: str, creative_id: str, params: dict) -> None:
        campaign = self._data["campaigns"].setdefault(campaign_name, {"fb_id": "", "params": {}, "ad_sets": {}})
        adset = campaign["ad_sets"].setdefault(adset_name, {"fb_id": "", "params": {}, "ads": {}})
        adset["ads"][ad_name] = {
            "fb_id": fb_id,
            "creative_id": creative_id,
            "params": params,
        }

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return dict(self._data)

    def campaigns(self) -> dict:
        return self._data["campaigns"]
