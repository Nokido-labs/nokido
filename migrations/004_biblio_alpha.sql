CREATE TABLE IF NOT EXISTS ideas (
    id              TEXT PRIMARY KEY,
    text            TEXT NOT NULL,
    parent_idea_id  TEXT REFERENCES ideas(id) ON DELETE SET NULL,
    superseded_by   TEXT REFERENCES ideas(id) ON DELETE SET NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS biblio_raw (
    id              TEXT PRIMARY KEY,
    type            TEXT CHECK(type IN ('book','paper','url','concept')),
    title           TEXT NOT NULL CHECK(length(title) >= 5),
    authors         TEXT,
    year            INTEGER CHECK(year IS NULL OR (year >= 1800 AND year <= 2030)),
    doi             TEXT,
    url             TEXT,
    pdf_url         TEXT,
    description     TEXT,
    triggered_by_idea_id  TEXT REFERENCES ideas(id) ON DELETE SET NULL,
    source_kind     TEXT CHECK(source_kind IN ('human_paste','agent_extract','agent_research')),
    payload_hash    TEXT NOT NULL UNIQUE,
    parent_hash     TEXT,
    status          TEXT DEFAULT 'unverified'
                    CHECK(status IN ('unverified','queued','searching','reviewed','promoted','rejected')),
    rejection_reason TEXT,
    search_results_json TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bibliography (
    id              TEXT PRIMARY KEY,
    promoted_from_raw_id TEXT NOT NULL REFERENCES biblio_raw(id),
    title           TEXT NOT NULL,
    authors         TEXT,
    year            INTEGER,
    doi             TEXT,
    url             TEXT,
    pdf_url         TEXT,
    description     TEXT,
    promoted_at     TEXT DEFAULT (datetime('now')),
    promoted_by     TEXT
);

CREATE INDEX IF NOT EXISTS idx_biblio_raw_status ON biblio_raw(status);
CREATE INDEX IF NOT EXISTS idx_biblio_raw_idea ON biblio_raw(triggered_by_idea_id);
CREATE INDEX IF NOT EXISTS idx_biblio_raw_doi ON biblio_raw(doi);
CREATE INDEX IF NOT EXISTS idx_biblio_promoted_from ON bibliography(promoted_from_raw_id);
CREATE INDEX IF NOT EXISTS idx_ideas_parent ON ideas(parent_idea_id);