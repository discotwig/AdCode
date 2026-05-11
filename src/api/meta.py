import logging
import time
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.adcreative import AdCreative
from facebook_business.exceptions import FacebookRequestError

logger = logging.getLogger(__name__)

# Error codes that warrant a retry with exponential backoff
_RETRYABLE_CODES = {4, 17, 32}  # 4=app limit, 17=user limit, 32=page limit
_MAX_RETRIES = 4
_BACKOFF_BASE = 2.0


def _with_retry(fn, *args, **kwargs):
    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except FacebookRequestError as exc:
            code = exc.api_error_code()
            if code not in _RETRYABLE_CODES:
                raise
            wait = _BACKOFF_BASE ** attempt
            logger.warning(
                "Rate limit hit (code %s); retrying in %.1fs (attempt %d/%d)",
                code, wait, attempt + 1, _MAX_RETRIES,
            )
            last_exc = exc
            time.sleep(wait)
    raise last_exc

CAMPAIGN_FIELDS = ["id", "name", "objective", "status", "special_ad_categories", "spend_cap", "daily_budget"]
ADSET_FIELDS = ["id", "name", "campaign_id", "status", "targeting", "billing_event",
                "optimization_goal", "bid_amount", "daily_budget", "lifetime_budget",
                "start_time", "end_time"]
AD_FIELDS = ["id", "name", "adset_id", "status", "creative"]


class MetaClient:
    def __init__(self, app_id: str, app_secret: str, access_token: str, account_id: str):
        FacebookAdsApi.init(app_id, app_secret, access_token)
        # account_id may arrive as "act_123" or plain "123" — normalise to "act_123"
        if not account_id.startswith("act_"):
            account_id = f"act_{account_id}"
        self.account_id = account_id
        self._account = AdAccount(account_id)

    # ------------------------------------------------------------------
    # Campaigns
    # ------------------------------------------------------------------

    def create_campaign(self, params: dict) -> str:
        # Required by the API when no campaign-level budget is set
        merged = {"is_adset_budget_sharing_enabled": False, **params}
        result = _with_retry(self._account.create_campaign, fields=[], params=merged)
        campaign_id = result["id"]
        logger.info("created campaign", extra={"fb_id": campaign_id, "name": params.get("name")})
        return campaign_id

    def update_campaign(self, campaign_id: str, params: dict) -> None:
        campaign = Campaign(campaign_id)
        _with_retry(campaign.api_update, params=params)
        logger.info("updated campaign", extra={"fb_id": campaign_id})

    def pause_campaign(self, campaign_id: str) -> None:
        self.update_campaign(campaign_id, {"status": "PAUSED"})
        logger.info("paused campaign", extra={"fb_id": campaign_id})

    def delete_campaign(self, campaign_id: str) -> None:
        campaign = Campaign(campaign_id)
        _with_retry(campaign.api_delete)
        logger.info("deleted campaign", extra={"fb_id": campaign_id})

    def get_campaign(self, campaign_id: str) -> dict:
        campaign = Campaign(campaign_id)
        _with_retry(campaign.api_get, fields=CAMPAIGN_FIELDS)
        return dict(campaign)

    def list_campaigns(self, account_id: str | None = None) -> list[dict]:
        account = AdAccount(account_id) if account_id else self._account
        campaigns = _with_retry(account.get_campaigns, fields=CAMPAIGN_FIELDS)
        return [dict(c) for c in campaigns]

    # ------------------------------------------------------------------
    # Ad Sets
    # ------------------------------------------------------------------

    def create_adset(self, campaign_id: str, params: dict) -> str:
        enriched = {**params, "campaign_id": campaign_id}
        result = _with_retry(self._account.create_ad_set, fields=[], params=enriched)
        adset_id = result["id"]
        logger.info("created adset", extra={"fb_id": adset_id, "campaign_id": campaign_id})
        return adset_id

    def update_adset(self, adset_id: str, params: dict) -> None:
        adset = AdSet(adset_id)
        _with_retry(adset.api_update, params=params)
        logger.info("updated adset", extra={"fb_id": adset_id})

    def get_adset(self, adset_id: str) -> dict:
        adset = AdSet(adset_id)
        _with_retry(adset.api_get, fields=ADSET_FIELDS)
        return dict(adset)

    def list_adsets(self, campaign_id: str) -> list[dict]:
        campaign = Campaign(campaign_id)
        adsets = _with_retry(campaign.get_ad_sets, fields=ADSET_FIELDS)
        return [dict(a) for a in adsets]

    # ------------------------------------------------------------------
    # Ads
    # ------------------------------------------------------------------

    def create_ad(self, adset_id: str, params: dict) -> str:
        enriched = {**params, "adset_id": adset_id}
        result = _with_retry(self._account.create_ad, fields=[], params=enriched)
        ad_id = result["id"]
        logger.info("created ad", extra={"fb_id": ad_id, "adset_id": adset_id})
        return ad_id

    def update_ad(self, ad_id: str, params: dict) -> None:
        ad = Ad(ad_id)
        _with_retry(ad.api_update, params=params)
        logger.info("updated ad", extra={"fb_id": ad_id})

    def get_ad(self, ad_id: str) -> dict:
        ad = Ad(ad_id)
        _with_retry(ad.api_get, fields=AD_FIELDS)
        return dict(ad)

    def list_ads(self, adset_id: str) -> list[dict]:
        adset = AdSet(adset_id)
        ads = _with_retry(adset.get_ads, fields=AD_FIELDS)
        return [dict(a) for a in ads]

    # ------------------------------------------------------------------
    # Creatives
    # ------------------------------------------------------------------

    def create_creative(self, params: dict) -> str:
        result = _with_retry(self._account.create_ad_creative, fields=[], params=params)
        creative_id = result["id"]
        logger.info("created creative", extra={"fb_id": creative_id})
        return creative_id
