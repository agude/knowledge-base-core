-- A synthetic Goose session database: the columns kb reads from Goose's sessions and messages
-- tables, with the measured shapes of their rows. Tests build sessions.db from this script.
-- Times are UTC: updated_at as SQLite's datetime('now') writes it, and created_timestamp in
-- seconds since the epoch. 1792918800 is 2026-10-25T09:00:00Z.

CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    working_dir TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    name TEXT DEFAULT '',
    session_type TEXT NOT NULL DEFAULT 'user',
    provider_name TEXT,
    archived_at TIMESTAMP,
    parent_session_id TEXT
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_timestamp INTEGER NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    tokens INTEGER,
    metadata_json TEXT,
    message_id TEXT
);

CREATE INDEX idx_messages_session_created ON messages(session_id, created_timestamp, id);

-- 20261025_3 has no messages. 20261025_4 ran through Claude Code, which keeps its own transcript.
INSERT INTO sessions (
    id, working_dir, created_at, updated_at, session_type, provider_name, parent_session_id
)
VALUES
    ('20261025_1', '/fixture/goose-project', '2026-10-25 09:00:00', '2026-10-25 09:05:00', 'user', 'openai', NULL),
    ('20261025_2', '/fixture/goose-project', '2026-10-25 09:01:00', '2026-10-25 09:03:00', 'sub_agent', 'openai', '20261025_1'),
    ('20261025_3', '/fixture/goose-project', '2026-10-25 09:02:00', '2026-10-25 09:02:00', 'acp', NULL, NULL),
    ('20261025_4', '/fixture/goose-project', '2026-10-25 09:04:00', '2026-10-25 09:04:00', 'user', 'claude-acp', NULL);

INSERT INTO messages (session_id, role, content_json, created_timestamp, metadata_json, message_id)
VALUES
    (
        '20261025_1', 'user',
        '[{"type":"text","text":"Summarize this Goose fixture."},'
        || '{"type":"text","text":"Drop this block for the agent alone.",'
        || '"annotations":{"audience":["assistant"]}}]',
        1792918800, '{"userVisible":true,"agentVisible":true}', 'goose-user-1'
    ),
    (
        '20261025_1', 'user',
        '[{"type":"text","text":"<turn-context>Drop this injected turn context.</turn-context>"}]',
        1792918800, '{"userVisible":false,"agentVisible":true,"turnContext":true}',
        'goose-context-1'
    ),
    (
        '20261025_1', 'assistant',
        '[{"type":"thinking","thinking":"Private reasoning must not be retained.","signature":""},'
        || '{"type":"text","text":"The Goose fixture has a main session."},'
        || '{"type":"toolRequest","id":"call-1","toolCall":{"status":"success","value":'
        || '{"name":"shell","arguments":{"command":"printf ''fixture command''"}}},'
        || '"_meta":{"goose_extension":"developer"}}]',
        1792918801, '{"userVisible":true,"agentVisible":true}', 'goose-assistant-1'
    ),
    (
        '20261025_1', 'user',
        '[{"type":"toolResponse","id":"call-1","toolResult":{"status":"success","value":'
        || '{"content":[{"type":"text","text":"Fixture tool output must not be retained.",'
        || '"annotations":{"priority":0.0}}],"isError":false,"resultType":"complete",'
        || '"structuredContent":{"stdout":"Fixture tool output must not be retained.",'
        || '"stderr":"","exit_code":0}}}}]',
        1792918802, '{"userVisible":true,"agentVisible":true}', 'goose-tool-1'
    ),
    (
        '20261025_1', 'assistant',
        '[{"type":"text","text":"Drop this compaction summary."}]',
        1792918803, '{"userVisible":false,"agentVisible":true}', 'goose-summary-1'
    ),
    (
        '20261025_1', 'assistant',
        '[{"type":"text","text":"The main session is done."}]',
        1792918804, '{"userVisible":true,"agentVisible":false}', 'goose-assistant-2'
    ),
    (
        '20261025_2', 'user',
        '[{"type":"text","text":"Check the subagent fixture."}]',
        1792918860, '{"userVisible":true,"agentVisible":true}', 'goose-agent-user'
    ),
    (
        '20261025_2', 'assistant',
        '[{"type":"text","text":"The subagent fixture is done."}]',
        1792918861, '{"userVisible":true,"agentVisible":true}', 'goose-agent-answer'
    ),
    (
        '20261025_4', 'user',
        '[{"type":"text","text":"Drop this proxied session."}]',
        1792919040, '{"userVisible":true,"agentVisible":true}', 'goose-proxied-user'
    );
