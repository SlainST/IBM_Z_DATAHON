"""Where points live. MemoryStore for tests and one-process laptops, PostgresStore for the server.

Each message is one transaction: lock the sender's row (and the A -> B row), check the message_id, write
the new points and the decision. Workers keep nothing between requests, so any worker on any server
gives the same answer. Platform and group counters are summed in each worker and written about once a
second, so they never make every message wait on the same row.
"""
import json
import logging
import threading
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ..engine.points import new_state

log = logging.getLogger("safenet.store")
SCHEMA = Path(__file__).with_name("schema.sql")
REPLY_DAYS = 7          # decisions per message_id are kept this long for retries


class StoreUnavailable(Exception):
    """Postgres unreachable, too slow or read-only: the API answers 503 + Retry-After."""


class Tx:
    def __init__(self, replay, user, relation):
        self.replay = replay
        self.user = user
        self.relation = relation
        self.saved = None

    def save(self, user: dict, relation: dict | None, answer: dict | None, counters: Counter):
        self.saved = (user, relation, answer, counters)


def _counter_rows(platform: str, group: str, counters: Counter):
    for grp in ("", group):
        for name, n in counters.items():
            yield platform, grp, name, n


def _stats(rows: dict, restricted_now: int) -> dict:
    messages = rows.get("messages", 0)
    harmful = rows.get("harmful", 0)
    pick = lambda prefix: {k.split(":", 1)[1]: v for k, v in sorted(rows.items()) if k.startswith(prefix)}
    return {"messages": messages, "harmful": harmful, "harmful_rate": round(harmful / messages, 4) if messages else 0.0,
            "decisions": pick("decision:"), "categories": pick("category:"), "reasons": pick("reason:"),
            "warnings": rows.get("warnings", 0), "restrictions": rows.get("restrictions", 0),
            "replayed": rows.get("replayed", 0), "restricted_now": restricted_now}


# ---- memory ----------------------------------------------------------------------------------------
class MemoryStore:
    kind = "memory"

    def __init__(self):
        self.lock = threading.Lock()
        self.users, self.relations, self.replies = {}, {}, {}
        self.counters: Counter = Counter()

    def open(self):
        pass

    def close(self):
        pass

    @contextmanager
    def message(self, platform, group, sender, recipient, message_id):
        with self.lock:
            replay = self.replies.get((platform, message_id)) if message_id else None
            user = dict(self.users.get((platform, group, sender)) or new_state())
            rel = None
            if recipient is not None:
                rel = dict(self.relations.get((platform, sender, recipient)) or new_state())
            tx = Tx(replay, user, rel)
            yield tx
            if tx.saved and not replay:
                user, rel, answer, counters = tx.saved
                self.users[(platform, group, sender)] = user
                if recipient is not None:
                    if rel and rel["points"] > 0:
                        self.relations[(platform, sender, recipient)] = rel
                    else:
                        self.relations.pop((platform, sender, recipient), None)
                if message_id and answer is not None:
                    self.replies[(platform, message_id)] = json.loads(json.dumps(answer, default=str))
                for row in _counter_rows(platform, group, counters):
                    self.counters[row[:3]] += row[3]

    def count(self, platform, group, counters: Counter):
        with self.lock:
            for row in _counter_rows(platform, group, counters):
                self.counters[row[:3]] += row[3]

    def user(self, platform, group, user_id):
        with self.lock:
            return dict(self.users.get((platform, group, user_id)) or new_state())

    def relation(self, platform, sender, recipient):
        with self.lock:
            return dict(self.relations.get((platform, sender, recipient)) or new_state())

    def stats(self, platform, group=None):
        now = datetime.now(timezone.utc)
        g = "" if group is None else group
        with self.lock:
            rows = {name: n for (p, grp, name), n in self.counters.items() if p == platform and grp == g}
            restricted = sum(1 for (p, grp, _), u in self.users.items()
                             if p == platform and (group is None or grp == group)
                             and u["restricted_until"] and u["restricted_until"] > now)
        return _stats(rows, restricted)

    def groups(self, platform, limit):
        with self.lock:
            rows = {}
            for (p, grp, name), n in self.counters.items():
                if p == platform and grp and name in ("messages", "harmful"):
                    rows.setdefault(grp, {"messages": 0, "harmful": 0})[name] = n
        ranked = sorted(rows.items(), key=lambda kv: (-kv[1]["harmful"], -kv[1]["messages"], kv[0]))[:limit]
        return [{"group": g, **v} for g, v in ranked]

    def writable(self) -> bool:
        return True


# ---- postgres --------------------------------------------------------------------------------------
class PostgresStore:
    kind = "postgres"

    def __init__(self, url: str, pool_size: int, timeout: float):
        self.url, self.pool_size, self.timeout = url, pool_size, timeout
        self.pool = None
        self.pending: Counter = Counter()
        self.pending_lock = threading.Lock()
        self._stop = threading.Event()
        self._flusher = None
        self._health = (0.0, False)

    def open(self):
        from psycopg_pool import ConnectionPool
        self.pool = ConnectionPool(self.url, min_size=1, max_size=self.pool_size, timeout=self.timeout,
                                   kwargs={"connect_timeout": max(1, int(self.timeout)), "application_name": "safenet"},
                                   open=False)
        self.pool.open(wait=False)
        try:
            with self.pool.connection(timeout=10) as conn, conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(735212)")
                conn.execute(SCHEMA.read_text(encoding="utf-8"))
        except Exception:
            log.exception("could not create the tables; /health will say so and /v1/check answers 503")
        self._flusher = threading.Thread(target=self._flush_loop, name="safenet-counters", daemon=True)
        self._flusher.start()

    def close(self):
        self._stop.set()
        if self._flusher:
            self._flusher.join(timeout=3)
        self._flush()
        if self.pool:
            self.pool.close()

    @contextmanager
    def _conn(self):
        import psycopg
        try:
            with self.pool.connection() as conn:
                yield conn
        except (psycopg.OperationalError, psycopg.errors.ReadOnlySqlTransaction,
                psycopg.errors.QueryCanceled, psycopg.errors.LockNotAvailable, TimeoutError) as e:
            raise StoreUnavailable(str(e)) from e
        except Exception as e:
            if type(e).__name__ == "PoolTimeout":
                raise StoreUnavailable(str(e)) from e
            raise

    @staticmethod
    def _state(row):
        if row is None:
            return new_state()
        points, recent, restrictions, until, messages = row
        return {"points": float(points), "recent": recent, "restrictions": restrictions,
                "restricted_until": until, "messages": messages}

    @contextmanager
    def message(self, platform, group, sender, recipient, message_id):
        with self._conn() as conn, conn.transaction():
            conn.execute("INSERT INTO users (platform, grp, user_id) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                         (platform, group, sender))
            user = self._state(conn.execute(
                "SELECT points, recent, restrictions, restricted_until, messages FROM users "
                "WHERE platform = %s AND grp = %s AND user_id = %s FOR UPDATE", (platform, group, sender)).fetchone())
            replay = None
            if message_id:
                row = conn.execute("SELECT answer FROM replies WHERE platform = %s AND message_id = %s",
                                   (platform, message_id)).fetchone()
                replay = row[0] if row else None
            rel = None
            if recipient is not None and replay is None:
                conn.execute("INSERT INTO relations (platform, sender, recipient) VALUES (%s, %s, %s) "
                             "ON CONFLICT DO NOTHING", (platform, sender, recipient))
                row = conn.execute(
                    "SELECT points, recent, 0, NULL::timestamptz, messages FROM relations "
                    "WHERE platform = %s AND sender = %s AND recipient = %s FOR UPDATE",
                    (platform, sender, recipient)).fetchone()
                rel = self._state(row)
            tx = Tx(replay, user, rel)
            yield tx
            if replay is not None or not tx.saved:
                return
            user, rel, answer, counters = tx.saved
            conn.execute("UPDATE users SET points = %s, recent = %s, restrictions = %s, restricted_until = %s, "
                         "messages = %s, updated_at = now() WHERE platform = %s AND grp = %s AND user_id = %s",
                         (user["points"], user["recent"], user["restrictions"], user["restricted_until"],
                          user["messages"], platform, group, sender))
            if recipient is not None:
                if rel and rel["points"] > 0:
                    conn.execute("UPDATE relations SET points = %s, recent = %s, messages = %s, updated_at = now() "
                                 "WHERE platform = %s AND sender = %s AND recipient = %s",
                                 (rel["points"], rel["recent"], rel["messages"], platform, sender, recipient))
                else:
                    conn.execute("DELETE FROM relations WHERE platform = %s AND sender = %s AND recipient = %s",
                                 (platform, sender, recipient))
            if message_id and answer is not None:
                conn.execute("INSERT INTO replies (platform, message_id, answer) VALUES (%s, %s, %s) "
                             "ON CONFLICT DO NOTHING", (platform, message_id, json.dumps(answer, default=str)))
        self.count(platform, group, counters)

    def count(self, platform, group, counters: Counter):
        with self.pending_lock:
            for row in _counter_rows(platform, group, counters):
                self.pending[row[:3]] += row[3]

    def _flush(self):
        with self.pending_lock:
            batch, self.pending = self.pending, Counter()
        if not batch or not self.pool:
            return
        try:
            with self.pool.connection(timeout=self.timeout) as conn, conn.transaction():
                with conn.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO counters (platform, grp, name, n) VALUES (%s, %s, %s, %s) "
                        "ON CONFLICT (platform, grp, name) DO UPDATE SET n = counters.n + EXCLUDED.n",
                        [(*k, n) for k, n in sorted(batch.items())])
        except Exception:
            log.warning("counters not written, retrying next second")
            with self.pending_lock:
                self.pending.update(batch)

    def _flush_loop(self):
        last_cleanup = 0.0
        while not self._stop.wait(1.0):
            self._flush()
            if time.monotonic() - last_cleanup > 600:
                last_cleanup = time.monotonic()
                try:
                    with self.pool.connection(timeout=self.timeout) as conn:
                        conn.execute("DELETE FROM replies WHERE created_at < now() - %s::interval",
                                     (f"{REPLY_DAYS} days",))
                        conn.commit()
                except Exception:
                    pass

    def user(self, platform, group, user_id):
        with self._conn() as conn:
            row = conn.execute("SELECT points, recent, restrictions, restricted_until, messages FROM users "
                               "WHERE platform = %s AND grp = %s AND user_id = %s", (platform, group, user_id)).fetchone()
            conn.rollback()
            return self._state(row)

    def relation(self, platform, sender, recipient):
        with self._conn() as conn:
            row = conn.execute("SELECT points, recent, 0, NULL::timestamptz, messages FROM relations "
                               "WHERE platform = %s AND sender = %s AND recipient = %s",
                               (platform, sender, recipient)).fetchone()
            conn.rollback()
            return self._state(row)

    def stats(self, platform, group=None):
        with self._conn() as conn:
            rows = dict(conn.execute("SELECT name, n FROM counters WHERE platform = %s AND grp = %s",
                                     (platform, "" if group is None else group)).fetchall())
            if group is None:
                restricted = conn.execute("SELECT count(*) FROM users WHERE platform = %s AND restricted_until > now()",
                                          (platform,)).fetchone()[0]
            else:
                restricted = conn.execute("SELECT count(*) FROM users WHERE platform = %s AND grp = %s "
                                          "AND restricted_until > now()", (platform, group)).fetchone()[0]
            conn.rollback()
        return _stats(rows, restricted)

    def groups(self, platform, limit):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT grp, coalesce(max(n) FILTER (WHERE name = 'messages'), 0), "
                "coalesce(max(n) FILTER (WHERE name = 'harmful'), 0) FROM counters "
                "WHERE platform = %s AND grp <> '' GROUP BY grp ORDER BY 3 DESC, 2 DESC, 1 LIMIT %s",
                (platform, limit)).fetchall()
            conn.rollback()
        return [{"group": g, "messages": m, "harmful": h} for g, m, h in rows]

    def writable(self) -> bool:
        checked, ok = self._health
        if time.monotonic() - checked < 1.0:
            return ok
        try:
            with self.pool.connection(timeout=1) as conn:
                ok = not conn.execute("SELECT pg_is_in_recovery()").fetchone()[0]
                conn.execute("SELECT 1 FROM users LIMIT 1")
                conn.rollback()
        except Exception:
            ok = False
        self._health = (time.monotonic(), ok)
        return ok


def make_store(url: str, pool_size: int, timeout: float):
    return PostgresStore(url, pool_size, timeout) if url else MemoryStore()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)

