import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

from app.integrations import base
from app.main import app


def _iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def amt(v):
    return {"value": f"{v:.2f}", "currency": "USD"}


ORDERS = [
    {"orderId": "11-11111-11111", "salesRecordReference": "1001", "creationDate": _iso(3), "lastModifiedDate": _iso(1),
     "orderFulfillmentStatus": "FULFILLED", "orderPaymentStatus": "PAID", "cancelStatus": {"cancelState": "NONE_REQUESTED"},
     "buyer": {"username": "trucker_joe", "buyerRegistrationAddress": {"fullName": "Joe Hauler", "email": "joe@relay.ebay.com",
               "primaryPhone": {"phoneNumber": "2185550199"}}},
     "pricingSummary": {"priceSubtotal": amt(40), "deliveryCost": amt(6.5), "tax": amt(0), "total": amt(46.5)},
     "paymentSummary": {"totalDueSeller": amt(40.1), "payments": [{"paymentMethod": "EBAY", "paymentStatus": "PAID",
                        "amount": amt(46.5), "paymentDate": _iso(3)}], "refunds": []},
     "totalMarketplaceFee": amt(6.4),
     "fulfillmentStartInstructions": [{"fulfillmentInstructionsType": "SHIP_TO", "shippingStep": {
         "shippingServiceCode": "USPSPriority", "shipTo": {"fullName": "Joe Hauler", "contactAddress": {
             "addressLine1": "1 Main St", "city": "Wadena", "stateOrProvince": "MN", "postalCode": "56482", "countryCode": "US"}}}}],
     "lineItems": [{"lineItemId": "L1", "title": "Forge Hoodie", "sku": "HD-L", "quantity": 1, "lineItemCost": amt(40),
                    "total": amt(46.5), "listingMarketplaceId": "EBAY_US", "legacyItemId": "2001",
                    "variationAspects": [{"name": "Size", "value": "L"}],
                    "ebayCollectAndRemitTaxes": [{"taxType": "STATE_SALES_TAX", "amount": amt(3.2)}]}]},
    {"orderId": "22-22222-22222", "creationDate": _iso(1), "lastModifiedDate": _iso(1),
     "orderFulfillmentStatus": "NOT_STARTED", "orderPaymentStatus": "PAID",
     "buyer": {"username": "new_buyer"}, "pricingSummary": {"priceSubtotal": amt(10), "total": amt(10)},
     "paymentSummary": {"payments": [], "refunds": []}, "totalMarketplaceFee": amt(1.5),
     "fulfillmentStartInstructions": [{"fulfillmentInstructionsType": "SHIP_TO"}],
     "lineItems": [{"lineItemId": "L2", "title": "Forge Decal", "quantity": 2, "lineItemCost": amt(10), "listingMarketplaceId": "EBAY_US"}]},
    {"orderId": "33-33333-33333", "creationDate": _iso(10), "lastModifiedDate": _iso(5),
     "orderFulfillmentStatus": "FULFILLED", "orderPaymentStatus": "FULLY_REFUNDED",
     "buyer": {"username": "trucker_joe"}, "pricingSummary": {"priceSubtotal": amt(20), "total": amt(20)},
     "paymentSummary": {"refunds": [{"refundId": "R1", "amount": amt(20), "refundStatus": "REFUNDED", "refundDate": _iso(5)}]},
     "lineItems": [{"lineItemId": "L3", "title": "Forge Mug", "quantity": 1, "lineItemCost": amt(20), "listingMarketplaceId": "EBAY_US"}]},
]


def handler(seen):
    def h(req: httpx.Request):
        seen.append(req)
        u = req.url
        if u.path == "/identity/v1/oauth2/token":
            form = dict(x.split("=", 1) for x in req.content.decode().split("&"))
            assert req.headers["authorization"].startswith("Basic ")
            if form["grant_type"] == "authorization_code":
                if form["code"] != "v%5E1.1%23CODE":     # urlencoded "v^1.1#CODE"
                    return httpx.Response(400, json={"error": "invalid_grant", "error_description": "bad code"})
                return httpx.Response(200, json={"access_token": "AT", "refresh_token": "RT", "refresh_token_expires_in": 47304000})
            if form["grant_type"] == "refresh_token":
                assert form["refresh_token"] == "RT"
                return httpx.Response(200, json={"access_token": "AT2", "expires_in": 7200})
            return httpx.Response(200, json={"access_token": "APP"})
        assert req.headers["authorization"] == "Bearer AT2"
        if u.path == "/sell/fulfillment/v1/order":
            assert "creationdate:[" in u.params["filter"] or "lastmodifieddate:[" in u.params["filter"]
            return httpx.Response(200, json={"total": 3, "orders": ORDERS})
        if u.path.endswith("/shipping_fulfillment"):
            oid = u.path.split("/")[-2]
            return httpx.Response(200, json={"fulfillments": [{"fulfillmentId": "F" + oid[:2], "shipmentTrackingNumber": "9400111",
                                  "shippingCarrierCode": "USPS", "shippedDate": _iso(2), "lineItems": [{"lineItemId": "L1"}]}]})
        return httpx.Response(404, json={})
    return h


def test_ebay_connect_sync_and_deletion(auth, monkeypatch):
    seen = []
    monkeypatch.setattr(base, "make_client", lambda: httpx.Client(transport=httpx.MockTransport(handler(seen))))
    r = auth.post("/api/integrations", json={"provider": "ebay", "values": {"client_id": "APPID", "client_secret": "CERT",
                                                                           "ru_name": "My-RuName"}})
    assert r.status_code == 201, r.text
    i = r.json()
    assert len(i["config"]["verification_token"]) >= 32 and i["saved_secrets"] == ["client_secret"]
    # not signed in yet -> readable error
    s = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert s["last_status"] == "error" and "Sign in with eBay" in s["last_error"]

    url = auth.get(f"/api/integrations/{i['id']}/ebay/authorize").json()["url"]
    assert url.startswith("https://auth.ebay.com/oauth2/authorize?") and "redirect_uri=My-RuName" in url
    assert "sell.fulfillment.readonly" in url and f"state={i['id']}." in url

    bad = auth.post(f"/api/integrations/{i['id']}/ebay/connect", json={"pasted": "hello"})
    assert bad.status_code == 422 and "code=" in bad.json()["detail"]
    pasted = "https://signin.ebay.com/ws/eBayISAPI.dll?ThirdPartyAuthSucessFailure&isAuthSuccessful=true&code=v%5E1.1%23CODE&expires_in=299"
    ok = auth.post(f"/api/integrations/{i['id']}/ebay/connect", json={"pasted": pasted})
    assert ok.status_code == 200, ok.text
    assert set(ok.json()["saved_secrets"]) == {"client_secret", "refresh_token"} and ok.json()["config"]["refresh_expires_at"]

    s = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert s["last_status"] == "ok", s["last_error"]
    assert s["last_result"]["orders_synced"] == 3 and s["last_result"]["revenue_synced"] == 56.5

    page = auth.get("/api/orders", params={"source": "ebay"}).json()
    assert page["total"] == 3 and page["summary"]["refunded"] == 20 and page["summary"]["fees"] == 7.9
    first = next(o for o in page["items"] if o["external_id"] == "11-11111-11111")
    assert first["reference"] == "1001" and first["customer_name"] == "Joe Hauler" and first["state"] == "COMPLETED"
    assert first["fulfillment_type"] == "SHIPMENT" and first["fulfillment_state"] == "SHIPPED"
    assert first["items_summary"] == "Forge Hoodie (L)" and first["service_charge_total"] == 6.5
    assert first["receipt_url"].endswith("orderid=11-11111-11111")
    detail = auth.get(f"/api/orders/{first['id']}").json()
    assert detail["payments"][0]["shipmentTrackingNumber"] == "9400111" and detail["raw"]["buyer"]["username"] == "trucker_joe"
    second = next(o for o in page["items"] if o["external_id"] == "22-22222-22222")
    assert second["state"] == "OPEN" and second["fulfillment_state"] == "NEEDS_SHIPPING"
    assert auth.get("/api/orders", params={"source": "square"}).json()["total"] == 0

    funnels = {f["name"]: f for f in auth.get("/api/funnels").json()}
    stages = {st["id"]: st["name"] for st in funnels["eBay Sales"]["stages"]}
    all_deals = auth.get("/api/deals", params={"funnel_id": funnels["eBay Sales"]["id"]}).json()
    by_stage = sorted(stages[d["stage_id"]] for d in all_deals)
    assert by_stage == ["Needs shipping", "Refunded / canceled", "Shipped"]
    contacts = auth.get("/api/contacts", params={"q": "Joe"}).json()["items"]
    assert len(contacts) == 1 and contacts[0]["email"] == "joe@relay.ebay.com"

    # second sync is incremental and does not duplicate
    s = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert s["last_status"] == "ok" and auth.get("/api/orders").json()["total"] == 3
    assert "lastmodifieddate" in [r for r in seen if r.url.path == "/sell/fulfillment/v1/order"][-1].url.params["filter"]

    # --- account deletion endpoint (public, no login)
    anon = TestClient(app)
    assert anon.get("/api/ebay/account-deletion", params={"challenge_code": "abc"}).status_code == 404   # no URL saved yet
    endpoint = "https://mserver.tail1234.ts.net/api/ebay/account-deletion"
    auth.patch(f"/api/integrations/{i['id']}", json={"values": {"deletion_endpoint": endpoint}})
    token = auth.get(f"/api/integrations/{i['id']}").json()["config"]["verification_token"]
    want = hashlib.sha256(("abc" + token + endpoint).encode()).hexdigest()
    for path in ("/api/ebay/account-deletion", "/api/ebay/api/ebay/account-deletion"):
        r = anon.get(path, params={"challenge_code": "abc"})
        assert r.status_code == 200 and r.headers["content-type"] == "application/json" and r.json() == {"challengeResponse": want}
    note = {"metadata": {"topic": "MARKETPLACE_ACCOUNT_DELETION"},
            "notification": {"notificationId": "n1", "data": {"username": "trucker_joe", "userId": "u1"}}}
    r = anon.post("/api/ebay/account-deletion", content=json.dumps(note), headers={"Content-Type": "application/json"})
    assert r.status_code == 204
    left = auth.get("/api/orders", params={"source": "ebay"}).json()
    assert left["total"] == 1 and left["items"][0]["buyer_username"] == "new_buyer"
    assert auth.get("/api/contacts", params={"q": "Joe"}).json()["items"] == []
    assert len(auth.get("/api/deals", params={"funnel_id": funnels["eBay Sales"]["id"]}).json()) == 1


def test_ebay_callback_page(auth, monkeypatch):
    seen = []
    monkeypatch.setattr(base, "make_client", lambda: httpx.Client(transport=httpx.MockTransport(handler(seen))))
    i = auth.post("/api/integrations", json={"provider": "ebay", "values": {"client_id": "A", "client_secret": "C", "ru_name": "R"}}).json()
    anon = TestClient(app)
    assert anon.get("/api/ebay/oauth/callback", params={"code": "x", "state": f"{i['id']}.forged"}).status_code == 400
    from app.integrations.ebay import make_state
    r = anon.get("/api/ebay/oauth/callback", params={"code": "v^1.1#CODE", "state": make_state(i["id"])})
    assert r.status_code == 200 and "eBay connected" in r.text
    assert "refresh_token" in auth.get(f"/api/integrations/{i['id']}").json()["saved_secrets"]
