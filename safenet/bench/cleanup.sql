-- Removes what bench/load_test.py wrote (ids start with bench_), so /v1/stats shows only real traffic.
-- psql "$SAFENET_DATABASE_URL" -f bench/cleanup.sql
BEGIN;
SET LOCAL statement_timeout = 0;
UPDATE counters c SET n = c.n - b.n
FROM (SELECT platform, name, sum(n) AS n FROM counters WHERE grp LIKE 'bench\_g%' GROUP BY platform, name) b
WHERE c.platform = b.platform AND c.grp = '' AND c.name = b.name;
DELETE FROM counters WHERE grp LIKE 'bench\_g%' OR n <= 0;
DELETE FROM users WHERE grp LIKE 'bench\_g%';
DELETE FROM relations WHERE sender LIKE 'bench\_u%';
DELETE FROM replies WHERE message_id LIKE 'bench\_%';
COMMIT;
