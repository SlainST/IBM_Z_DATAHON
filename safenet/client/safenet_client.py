"""SafeNet client for platform adapters: one file, standard library only, so it can be copied next to any
adapter (WhatsApp bridge, YouTube moderator, notebook test). docs/API.md describes every field.

    from safenet_client import SafeNet
    sn = SafeNet("http://127.0.0.1:8000", key=os.environ["SAFENET_KEY"])   # deploy/linuxone/tunnel.sh
    answer = sn.check("u_4821", "f*ck, I missed the bus", recipient="u_1093", group="t_77")
    if answer["decision"] in ("allow", "censor"):
        deliver(answer["recipient_sees"])

Retries: every message gets a message_id (a new uuid unless given), and a 503 or a broken connection is retried
with the same id, waiting Retry-After, so a message is never counted twice. When SafeNet cannot answer at all,
check() returns `unavailable_decision` ("hold" by default: the safe choice for children) with
reason "safenet_unavailable" instead of raising, so the platform can keep the message back.
The key is never printed or logged.
"""
import json
import time
import urllib.error
import urllib.request
import uuid

UNAVAILABLE = "safenet_unavailable"


class SafeNetError(Exception):
    """A 4xx answer: a wrong key (401), a platform without settings (403) or an invalid body (422)."""

    def __init__(self, status: int, detail):
        super().__init__(f"{status}: {detail}")
        self.status, self.detail = status, detail


class SafeNet:
    def __init__(self, url: str = "http://127.0.0.1:8000", key: str | None = None, timeout: float = 2.0,
                 retries: int = 3, unavailable_decision: str = "hold"):
        self.url = url.rstrip("/")
        self._key = key
        self.timeout, self.retries = timeout, retries
        self.unavailable_decision = unavailable_decision

    def __repr__(self) -> str:
        return f"SafeNet({self.url!r}, key={'set' if self._key else None})"

    # ---- messages ---------------------------------------------------------------------------------------------
    def check(self, sender: str, text: str, recipient: str | None = None, group: str = "general",
              message_id: str | None = None) -> dict:
        """What may the recipient see? Never raises for an unreachable SafeNet (see the module docstring)."""
        body = {"sender_id": sender, "text": text, "group_id": group, "message_id": message_id or uuid.uuid4().hex}
        if recipient is not None:
            body["recipient_id"] = recipient
        try:
            return self._call("POST", "/v1/check", body)
        except (OSError, TimeoutError):
            return {"decision": self.unavailable_decision, "recipient_sees": None, "reason": UNAVAILABLE,
                    "message_id": body["message_id"], "sender": sender, "recipient": recipient, "group": group}

    def check_batch(self, messages: list[dict]) -> list[dict]:
        """Up to SAFENET_MAX_BATCH messages ({"sender_id", "text", ...}), answered in order. Raises when SafeNet
        cannot answer: resend the same list, every message keeps its message_id."""
        for m in messages:
            m.setdefault("message_id", uuid.uuid4().hex)
        return self._call("POST", "/v1/check/batch", {"messages": messages})["results"]

    # ---- moderators and dashboards ------------------------------------------------------------------------------
    def user(self, group: str, user: str) -> dict:
        return self._call("GET", f"/v1/groups/{_quote(group)}/users/{_quote(user)}")

    def relation(self, sender: str, recipient: str) -> dict:
        return self._call("GET", f"/v1/relations/{_quote(sender)}/{_quote(recipient)}")

    def stats(self, group: str | None = None) -> dict:
        return self._call("GET", "/v1/stats" if group is None else f"/v1/groups/{_quote(group)}/stats")

    def groups(self, limit: int = 50) -> list[dict]:
        return self._call("GET", f"/v1/groups?limit={int(limit)}")["groups"]

    def settings(self) -> dict:
        return self._call("GET", "/v1/settings")

    def health(self) -> dict:
        """No key needed. Answers even while the store is down (then with status "degraded")."""
        return self._call("GET", "/health", keyed=False, accept=(200, 503))

    # ---- transport ------------------------------------------------------------------------------------------------
    def _call(self, method: str, path: str, body: dict | None = None, keyed: bool = True, accept=(200,)):
        headers = {"Accept": "application/json"}
        if keyed and self._key:
            headers["X-API-Key"] = self._key
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        last: Exception | None = None
        for attempt in range(self.retries):
            request = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                payload = _json(e.read())
                if e.code in accept:
                    return payload
                if e.code != 503:
                    raise SafeNetError(e.code, payload.get("detail", payload)) from None
                last = e
                time.sleep(float(e.headers.get("Retry-After", 1)))
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = e
                time.sleep(0.2 * (attempt + 1))
        raise ConnectionError(f"SafeNet at {self.url} did not answer after {self.retries} tries: {last}")


def _quote(part: str) -> str:
    return urllib.request.quote(part, safe="")


def _json(raw: bytes) -> dict:
    try:
        return json.loads(raw)
    except ValueError:
        return {"detail": raw.decode(errors="replace")}
