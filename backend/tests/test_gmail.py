import imaplib
import re
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime

from app.integrations import gmail


def _msg(frm, to, subject, body, days_ago, html=None, extra=None, attach=None):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, to, subject
    m["Date"] = format_datetime(datetime.now(timezone.utc) - timedelta(days=days_ago))
    m["Message-ID"] = f"<{abs(hash(subject))}@x>"
    for k, v in (extra or {}).items():
        m[k] = v
    m.set_content(body)
    if html:
        m.add_alternative(html, subtype="html")
    if attach:
        m.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename=attach)
    return m.as_bytes()


MAILBOX = {
    101: (_msg("Me <me@gmail.com>", "Jake Miller <jake@example.com>", "Hoodie quote", "Hi Jake, $40 each.", 5, attach="quote.pdf"),
          b'(\\Sent)', 9001, 7001),
    102: (_msg("Jake Miller <jake@example.com>", "me@gmail.com", "Re: Hoodie quote", "Sounds good, order 3.", 4,
               html="<p>Sounds <b>good</b>, order 3.</p><img src='https://track.example/p.gif'>"), b'(\\Inbox "Customers")', 9001, 7002),
    103: (_msg("Deals <news@shop.example>", "me@gmail.com", "50% off", "Sale!", 3, extra={"List-Unsubscribe": "<mailto:u@x>"}),
          b'(\\Inbox)', 9002, 7003),
    104: (_msg("Sam Ortiz <sam@example.com>", "me@gmail.com", "Question about pickup", "When can I pick up?", 2), b'(\\Inbox)', 9003, 7004),
}


class FakeIMAP:
    logins = []

    def __init__(self, host):
        self.host = host
        self.mail = dict(MAILBOX)

    def login(self, user, pw):
        FakeIMAP.logins.append((user, pw))
        if pw != "abcdefghijklmnop":
            raise imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)")
        return "OK", [b"ok"]

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"']

    def select(self, folder, readonly=False):
        assert folder == '"[Gmail]/All Mail"' and readonly
        return "OK", [b"4"]

    def response(self, code):
        return "UIDVALIDITY", [b"555"]

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            args = [a for a in args if a is not None]
            uids = sorted(self.mail)
            if args[0] == "UID":
                lo = int(args[1].split(":")[0])
                uids = [u for u in uids if u >= lo] or [max(self.mail)]   # IMAP returns the last message for n:*
            return "OK", [" ".join(map(str, uids)).encode()]
        if cmd == "FETCH":
            want = [int(x) for x in args[0].split(",")]
            out = []
            for i, u in enumerate(want):
                raw, labels, thr, gm = self.mail[u]
                if "RFC822.SIZE" in args[1]:
                    out.append(f"{i+1} (X-GM-THRID {thr} X-GM-MSGID {gm} X-GM-LABELS ".encode() + labels +
                               f" UID {u} FLAGS ({'' if u == 104 else chr(92) + 'Seen'}) RFC822.SIZE {len(raw)})".encode())
                else:
                    body = raw if "BODY.PEEK[]" in args[1] else raw.split(b"\n\n")[0]
                    out.append((f"{i+1} (UID {u} BODY[] {{{len(body)}}}".encode(), body))
                    out.append(b")")
            return "OK", out
        raise AssertionError(cmd)

    def logout(self):
        return "BYE", []


def test_gmail_sync(auth, monkeypatch):
    monkeypatch.setattr(gmail, "make_imap", FakeIMAP)
    jake = auth.post("/api/contacts", json={"first_name": "Jake", "last_name": "Miller", "email": "Jake@Example.com"}).json()
    r = auth.post("/api/integrations", json={"provider": "gmail", "values": {"email": "me@gmail.com", "app_password": "wrong"}})
    i = r.json()
    s = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert s["last_status"] == "error" and "app password" in s["last_error"]
    auth.patch(f"/api/integrations/{i['id']}", json={"values": {"app_password": "abcd efgh ijkl mnop"}})
    t = auth.post(f"/api/integrations/{i['id']}/test").json()
    assert t["ok"], t
    s = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert s["last_status"] == "ok", s["last_error"]
    assert s["last_result"]["emails_sent"] == 1 and s["last_result"]["emails_received"] == 3
    assert FakeIMAP.logins[-1] == ("me@gmail.com", "abcdefghijklmnop")

    page = auth.get("/api/emails").json()
    assert page["total"] == 4
    by_subj = {e["subject"]: e for e in page["items"]}
    q = by_subj["Hoodie quote"]
    assert q["direction"] == "out" and q["contact_id"] == jake["id"] and q["attachment_count"] == 1
    assert q["gmail_url"].endswith(f"#all/{9001 - 9001 + 7001:x}")
    re_ = by_subj["Re: Hoodie quote"]
    assert re_["direction"] == "in" and re_["contact_id"] == jake["id"] and re_["contact_name"] == "Jake Miller"
    assert by_subj["50% off"]["bulk"] and by_subj["50% off"]["contact_id"] is None
    # default "emailed" policy: Sam emailed us but we never wrote to Sam -> no new contact
    assert by_subj["Question about pickup"]["contact_id"] is None and by_subj["Question about pickup"]["unread"]
    assert auth.get("/api/emails", params={"include_bulk": "false"}).json()["total"] == 3
    assert auth.get("/api/emails", params={"contact_id": jake["id"]}).json()["total"] == 2

    d = auth.get(f"/api/emails/{re_['id']}").json()
    assert "<b>good</b>" in d["body_html"] and "Sounds good" in d["body_text"]
    assert [t["subject"] for t in d["thread"]] == ["Hoodie quote", "Re: Hoodie quote"]
    assert auth.get(f"/api/emails/{q['id']}").json()["attachments"][0]["name"] == "quote.pdf"

    # manual link
    sam = auth.post("/api/contacts", json={"first_name": "Sam", "email": "sam@example.com"}).json()
    pick = by_subj["Question about pickup"]
    assert auth.patch(f"/api/emails/{pick['id']}", json={"contact_id": sam["id"]}).json()["contact_name"] == "Sam"

    # incremental: nothing new -> nothing duplicated; then a new message arrives
    s = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert s["last_status"] == "ok" and auth.get("/api/emails").json()["total"] == 4
    MAILBOX[105] = (_msg("Sam Ortiz <sam@example.com>", "me@gmail.com", "Thanks", "Got it", 0), b'(\\Inbox)', 9003, 7005)
    try:
        s = auth.post(f"/api/integrations/{i['id']}/sync").json()
        assert s["last_result"].get("emails_received") == 1
        new = auth.get("/api/emails", params={"q": "Got it"}).json()["items"][0]
        assert new["contact_id"] == sam["id"]
    finally:
        MAILBOX.pop(105)


def test_gmail_create_all(auth, monkeypatch):
    monkeypatch.setattr(gmail, "make_imap", FakeIMAP)
    i = auth.post("/api/integrations", json={"provider": "gmail", "values": {
        "email": "me@gmail.com", "app_password": "abcdefghijklmnop", "create_contacts": "all"}}).json()
    assert auth.post(f"/api/integrations/{i['id']}/sync").json()["last_status"] == "ok"
    emails = {c["email"] for c in auth.get("/api/contacts").json()["items"]}
    assert emails == {"jake@example.com", "sam@example.com"}      # newsletter skipped
