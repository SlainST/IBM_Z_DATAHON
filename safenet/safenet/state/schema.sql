-- SafeNet state. Message text is never stored: only points, counters, the last clean / not-clean bits
-- and, per message_id, the decision (for retries). Created on the API's first start.

CREATE TABLE IF NOT EXISTS users (
    platform         text NOT NULL,
    grp              text NOT NULL,
    user_id          text NOT NULL,
    points           double precision NOT NULL DEFAULT 0,
    recent           varchar(32) NOT NULL DEFAULT '',     -- '1' clean, '0' not, newest last
    restrictions     integer NOT NULL DEFAULT 0,
    restricted_until timestamptz,
    messages         bigint NOT NULL DEFAULT 0,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (platform, grp, user_id)
);
CREATE INDEX IF NOT EXISTS users_restricted ON users (platform, restricted_until) WHERE restricted_until IS NOT NULL;

-- A -> B, platform-wide. A row exists only while its points are above 0.
CREATE TABLE IF NOT EXISTS relations (
    platform     text NOT NULL,
    sender       text NOT NULL,
    recipient    text NOT NULL,
    points       double precision NOT NULL DEFAULT 0,
    recent       varchar(32) NOT NULL DEFAULT '',
    messages     bigint NOT NULL DEFAULT 0,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (platform, sender, recipient)
);

-- The decision per message_id, without any text, so a retry gets the same answer and counts nothing twice.
CREATE TABLE IF NOT EXISTS replies (
    platform    text NOT NULL,
    message_id  text NOT NULL,
    answer      jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (platform, message_id)
);

-- grp = '' is the whole platform.
CREATE TABLE IF NOT EXISTS counters (
    platform  text NOT NULL,
    grp       text NOT NULL,
    name      text NOT NULL,
    n         bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (platform, grp, name)
);
