from fastapi.testclient import TestClient

from cosmos.public.api.app import app

client = TestClient(app)
accounts_auth_headers = {"Bpl-User-Channel": "channel"}  # FIXME: Check if this is needed
test_campaign_slug = "test-campaign-slug"
test_campaign_slug = "test-campaign-slug"
