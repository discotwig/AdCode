import pytest
from unittest.mock import MagicMock, patch, call
from facebook_business.exceptions import FacebookRequestError

from src.api.meta import MetaClient


@pytest.fixture
def client(mocker):
    mocker.patch("src.api.meta.FacebookAdsApi.init")
    mocker.patch("src.api.meta.AdAccount")
    return MetaClient("app_id", "app_secret", "access_token", "act_123456789")


@pytest.fixture
def client_bare_id(mocker):
    mocker.patch("src.api.meta.FacebookAdsApi.init")
    mocker.patch("src.api.meta.AdAccount")
    return MetaClient("app_id", "app_secret", "access_token", "123456789")


class TestInit:
    def test_account_id_normalised_with_act_prefix(self, mocker):
        mocker.patch("src.api.meta.FacebookAdsApi.init")
        mocker.patch("src.api.meta.AdAccount")
        c = MetaClient("app_id", "app_secret", "token", "123456789")
        assert c.account_id == "act_123456789"

    def test_account_id_with_act_prefix_unchanged(self, mocker):
        mocker.patch("src.api.meta.FacebookAdsApi.init")
        mocker.patch("src.api.meta.AdAccount")
        c = MetaClient("app_id", "app_secret", "token", "act_123456789")
        assert c.account_id == "act_123456789"


class TestCampaigns:
    def test_create_campaign_returns_id(self, client, mocker):
        mock_result = MagicMock()
        mock_result.__getitem__ = lambda self, key: "camp_001" if key == "id" else None
        client._account.create_campaign.return_value = mock_result

        campaign_id = client.create_campaign({"name": "Test", "objective": "OUTCOME_TRAFFIC"})

        assert campaign_id == "camp_001"
        client._account.create_campaign.assert_called_once()

    def test_update_campaign_calls_api_update(self, client, mocker):
        mock_campaign = MagicMock()
        mocker.patch("src.api.meta.Campaign", return_value=mock_campaign)

        client.update_campaign("camp_001", {"status": "PAUSED"})

        mock_campaign.api_update.assert_called_once_with(params={"status": "PAUSED"})

    def test_pause_campaign_sets_paused_status(self, client, mocker):
        mock_campaign = MagicMock()
        mocker.patch("src.api.meta.Campaign", return_value=mock_campaign)

        client.pause_campaign("camp_001")

        mock_campaign.api_update.assert_called_once()
        call_kwargs = mock_campaign.api_update.call_args[1]
        assert call_kwargs["params"]["status"] == "PAUSED"

    def test_get_campaign_returns_dict(self, client, mocker):
        mock_campaign = MagicMock()
        mock_campaign.__iter__ = lambda self: iter([("id", "camp_001"), ("name", "Test")])
        mocker.patch("src.api.meta.Campaign", return_value=mock_campaign)

        result = client.get_campaign("camp_001")

        mock_campaign.api_get.assert_called_once()
        assert isinstance(result, dict)

    def test_list_campaigns_returns_list_of_dicts(self, client, mocker):
        mock_c1 = MagicMock()
        mock_c1.__iter__ = lambda self: iter([("id", "c1"), ("name", "Camp 1")])
        mock_c2 = MagicMock()
        mock_c2.__iter__ = lambda self: iter([("id", "c2"), ("name", "Camp 2")])
        client._account.get_campaigns.return_value = [mock_c1, mock_c2]

        result = client.list_campaigns()

        assert len(result) == 2
        assert all(isinstance(r, dict) for r in result)

    def test_list_campaigns_uses_provided_account_id(self, client, mocker):
        mock_account = MagicMock()
        mock_account.get_campaigns.return_value = []
        mocker.patch("src.api.meta.AdAccount", return_value=mock_account)

        client.list_campaigns(account_id="act_999")

        mock_account.get_campaigns.assert_called_once()


class TestAdSets:
    def test_create_adset_injects_campaign_id(self, client, mocker):
        mock_result = MagicMock()
        mock_result.__getitem__ = lambda self, key: "adset_001" if key == "id" else None
        client._account.create_ad_set.return_value = mock_result

        adset_id = client.create_adset("camp_001", {"name": "Test AdSet"})

        assert adset_id == "adset_001"
        call_kwargs = client._account.create_ad_set.call_args[1]
        assert call_kwargs["params"]["campaign_id"] == "camp_001"

    def test_update_adset_calls_api_update(self, client, mocker):
        mock_adset = MagicMock()
        mocker.patch("src.api.meta.AdSet", return_value=mock_adset)

        client.update_adset("adset_001", {"daily_budget": 5000})

        mock_adset.api_update.assert_called_once_with(params={"daily_budget": 5000})

    def test_get_adset_returns_dict(self, client, mocker):
        mock_adset = MagicMock()
        mock_adset.__iter__ = lambda self: iter([("id", "adset_001")])
        mocker.patch("src.api.meta.AdSet", return_value=mock_adset)

        result = client.get_adset("adset_001")

        mock_adset.api_get.assert_called_once()
        assert isinstance(result, dict)

    def test_list_adsets_returns_list_of_dicts(self, client, mocker):
        mock_a1 = MagicMock()
        mock_a1.__iter__ = lambda self: iter([("id", "a1")])
        mock_campaign = MagicMock()
        mock_campaign.get_ad_sets.return_value = [mock_a1]
        mocker.patch("src.api.meta.Campaign", return_value=mock_campaign)

        result = client.list_adsets("camp_001")

        assert len(result) == 1
        assert isinstance(result[0], dict)


class TestAds:
    def test_create_ad_injects_adset_id(self, client, mocker):
        mock_result = MagicMock()
        mock_result.__getitem__ = lambda self, key: "ad_001" if key == "id" else None
        client._account.create_ad.return_value = mock_result

        ad_id = client.create_ad("adset_001", {"name": "Test Ad"})

        assert ad_id == "ad_001"
        call_kwargs = client._account.create_ad.call_args[1]
        assert call_kwargs["params"]["adset_id"] == "adset_001"

    def test_update_ad_calls_api_update(self, client, mocker):
        mock_ad = MagicMock()
        mocker.patch("src.api.meta.Ad", return_value=mock_ad)

        client.update_ad("ad_001", {"status": "PAUSED"})

        mock_ad.api_update.assert_called_once_with(params={"status": "PAUSED"})

    def test_get_ad_returns_dict(self, client, mocker):
        mock_ad = MagicMock()
        mock_ad.__iter__ = lambda self: iter([("id", "ad_001")])
        mocker.patch("src.api.meta.Ad", return_value=mock_ad)

        result = client.get_ad("ad_001")

        mock_ad.api_get.assert_called_once()
        assert isinstance(result, dict)

    def test_list_ads_returns_list_of_dicts(self, client, mocker):
        mock_ad = MagicMock()
        mock_ad.__iter__ = lambda self: iter([("id", "ad_001")])
        mock_adset = MagicMock()
        mock_adset.get_ads.return_value = [mock_ad]
        mocker.patch("src.api.meta.AdSet", return_value=mock_adset)

        result = client.list_ads("adset_001")

        assert len(result) == 1
        assert isinstance(result[0], dict)


class TestCreatives:
    def test_create_creative_returns_id(self, client, mocker):
        mock_result = MagicMock()
        mock_result.__getitem__ = lambda self, key: "creative_001" if key == "id" else None
        client._account.create_ad_creative.return_value = mock_result

        creative_id = client.create_creative({"name": "Test Creative", "object_story_spec": {}})

        assert creative_id == "creative_001"
        client._account.create_ad_creative.assert_called_once()


class TestErrorPropagation:
    def test_non_retryable_error_propagates_immediately(self, client, mocker):
        error = FacebookRequestError(
            message="Invalid parameter",
            request_context={},
            http_status=400,
            http_headers={},
            body={"error": {"code": 100, "message": "Invalid parameter"}},
        )
        client._account.create_campaign.side_effect = error

        with pytest.raises(FacebookRequestError):
            client.create_campaign({"name": "Test"})

        # Should only be called once — no retries for non-retryable codes
        client._account.create_campaign.assert_called_once()

    def test_update_campaign_non_retryable_error_propagates(self, client, mocker):
        mock_campaign = MagicMock()
        mock_campaign.api_update.side_effect = FacebookRequestError(
            message="Invalid parameter",
            request_context={},
            http_status=400,
            http_headers={},
            body={"error": {"code": 100, "message": "Invalid parameter"}},
        )
        mocker.patch("src.api.meta.Campaign", return_value=mock_campaign)

        with pytest.raises(FacebookRequestError):
            client.update_campaign("camp_001", {"invalid_field": "value"})


class TestRetryLogic:
    def _rate_limit_error(self, code: int = 32) -> FacebookRequestError:
        return FacebookRequestError(
            message="Rate limit",
            request_context={},
            http_status=400,
            http_headers={},
            body={"error": {"code": code, "message": "Rate limit"}},
        )

    def test_retries_on_code_32(self, client, mocker):
        mocker.patch("src.api.meta.time.sleep")
        mock_result = MagicMock()
        mock_result.__getitem__ = lambda self, key: "camp_001" if key == "id" else None
        client._account.create_campaign.side_effect = [
            self._rate_limit_error(32),
            mock_result,
        ]

        camp_id = client.create_campaign({"name": "Test"})

        assert camp_id == "camp_001"
        assert client._account.create_campaign.call_count == 2

    def test_retries_on_code_17(self, client, mocker):
        mocker.patch("src.api.meta.time.sleep")
        mock_result = MagicMock()
        mock_result.__getitem__ = lambda self, key: "camp_001" if key == "id" else None
        client._account.create_campaign.side_effect = [
            self._rate_limit_error(17),
            mock_result,
        ]

        camp_id = client.create_campaign({"name": "Test"})

        assert camp_id == "camp_001"
        assert client._account.create_campaign.call_count == 2

    def test_raises_after_max_retries_exhausted(self, client, mocker):
        mocker.patch("src.api.meta.time.sleep")
        client._account.create_campaign.side_effect = self._rate_limit_error(32)

        with pytest.raises(FacebookRequestError):
            client.create_campaign({"name": "Test"})

        assert client._account.create_campaign.call_count == 4  # _MAX_RETRIES

    def test_sleeps_between_retries(self, client, mocker):
        sleep_mock = mocker.patch("src.api.meta.time.sleep")
        mock_result = MagicMock()
        mock_result.__getitem__ = lambda self, key: "camp_001" if key == "id" else None
        client._account.create_campaign.side_effect = [
            self._rate_limit_error(32),
            self._rate_limit_error(32),
            mock_result,
        ]

        client.create_campaign({"name": "Test"})

        assert sleep_mock.call_count == 2
