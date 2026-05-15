CREATE TABLE IF NOT EXISTS market_bars (
    symbol TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open NUMERIC(18, 6) NOT NULL,
    high NUMERIC(18, 6) NOT NULL,
    low NUMERIC(18, 6) NOT NULL,
    close NUMERIC(18, 6) NOT NULL,
    volume BIGINT NOT NULL,
    value NUMERIC(24, 6) NOT NULL,
    source TEXT NOT NULL DEFAULT 'dummy',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, timestamp),
    CONSTRAINT market_bars_volume_nonnegative CHECK (volume >= 0),
    CONSTRAINT market_bars_value_nonnegative CHECK (value >= 0),
    CONSTRAINT market_bars_high_low CHECK (high >= low),
    CONSTRAINT market_bars_high_open CHECK (high >= open),
    CONSTRAINT market_bars_high_close CHECK (high >= close),
    CONSTRAINT market_bars_low_open CHECK (low <= open),
    CONSTRAINT market_bars_low_close CHECK (low <= close)
);

CREATE INDEX IF NOT EXISTS idx_market_bars_symbol_timestamp
    ON market_bars (symbol, timestamp);

CREATE TABLE IF NOT EXISTS index_bars (
    index_code TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open NUMERIC(18, 6) NOT NULL,
    high NUMERIC(18, 6) NOT NULL,
    low NUMERIC(18, 6) NOT NULL,
    close NUMERIC(18, 6) NOT NULL,
    volume BIGINT NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'sample',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (index_code, timestamp),
    CONSTRAINT index_bars_volume_nonnegative CHECK (volume >= 0),
    CONSTRAINT index_bars_high_low CHECK (high >= low),
    CONSTRAINT index_bars_high_open CHECK (high >= open),
    CONSTRAINT index_bars_high_close CHECK (high >= close),
    CONSTRAINT index_bars_low_open CHECK (low <= open),
    CONSTRAINT index_bars_low_close CHECK (low <= close)
);

CREATE INDEX IF NOT EXISTS idx_index_bars_code_timestamp
    ON index_bars (index_code, timestamp);

CREATE TABLE IF NOT EXISTS symbol_metadata (
    symbol TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    market TEXT NOT NULL,
    section_kind TEXT NOT NULL DEFAULT '',
    status_kind TEXT NOT NULL DEFAULT '',
    control_kind TEXT NOT NULL DEFAULT '',
    supervision_kind TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'sample',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dry_run_sessions (
    session_id TEXT PRIMARY KEY,
    trading_date DATE NOT NULL,
    package_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    order_hard_block BOOLEAN NOT NULL,
    summary JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT dry_run_sessions_no_order_mode CHECK (mode = 'no-order'),
    CONSTRAINT dry_run_sessions_order_hard_block CHECK (order_hard_block = true),
    CONSTRAINT dry_run_sessions_not_broker_ready
        CHECK (
            COALESCE(
                jsonb_typeof(summary -> 'ready_for_broker_or_order_transmission') = 'boolean'
                AND summary -> 'ready_for_broker_or_order_transmission' = 'false'::jsonb,
                false
            )
        )
);

CREATE TABLE IF NOT EXISTS dry_run_ledger_events (
    session_id TEXT NOT NULL REFERENCES dry_run_sessions(session_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    event_time TIMESTAMPTZ,
    symbol TEXT NOT NULL DEFAULT '',
    strategy_group TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, sequence),
    CONSTRAINT dry_run_ledger_events_sequence_positive CHECK (sequence > 0),
    CONSTRAINT dry_run_ledger_session_summary_not_broker_ready
        CHECK (
            event_type <> 'session-summary'
            OR (
                COALESCE(
                    jsonb_typeof(payload -> 'ready_for_broker_or_order_transmission') = 'boolean'
                    AND payload -> 'ready_for_broker_or_order_transmission' = 'false'::jsonb,
                    false
                )
            )
        ),
    CONSTRAINT dry_run_ledger_virtual_order_hard_block
        CHECK (
            event_type <> 'virtual-order'
            OR (
                COALESCE(
                    jsonb_typeof(payload -> 'hard_blocked') = 'boolean'
                    AND payload -> 'hard_blocked' = 'true'::jsonb,
                    false
                )
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_dry_run_ledger_events_session_type
    ON dry_run_ledger_events (session_id, event_type, sequence);
