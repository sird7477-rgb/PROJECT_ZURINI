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

CREATE TABLE IF NOT EXISTS index_ticks (
    index_code TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    price NUMERIC(18, 6) NOT NULL,
    session_open NUMERIC(18, 6),
    session_high NUMERIC(18, 6),
    session_low NUMERIC(18, 6),
    volume BIGINT NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'kis-index-poll-10s',
    vendor TEXT NOT NULL DEFAULT 'kis',
    source_run_id TEXT NOT NULL DEFAULT 'field-run',
    poll_interval_seconds INTEGER NOT NULL DEFAULT 10,
    quality_flags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    raw_payload JSONB,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (index_code, timestamp, source, vendor, source_run_id),
    CONSTRAINT index_ticks_price_positive CHECK (price > 0),
    CONSTRAINT index_ticks_volume_nonnegative CHECK (volume >= 0),
    CONSTRAINT index_ticks_poll_interval_positive CHECK (poll_interval_seconds > 0),
    CONSTRAINT index_ticks_session_high_low
        CHECK (
            session_high IS NULL
            OR session_low IS NULL
            OR session_high >= session_low
        )
);

CREATE INDEX IF NOT EXISTS idx_index_ticks_code_timestamp
    ON index_ticks (index_code, timestamp);

CREATE TABLE IF NOT EXISTS index_bars (
    index_code TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open NUMERIC(18, 6) NOT NULL,
    high NUMERIC(18, 6) NOT NULL,
    low NUMERIC(18, 6) NOT NULL,
    close NUMERIC(18, 6) NOT NULL,
    volume BIGINT NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'sample',
    vendor TEXT NOT NULL DEFAULT 'sample',
    source_run_id TEXT NOT NULL DEFAULT 'sample-run',
    import_batch_id TEXT NOT NULL DEFAULT 'sample-batch',
    schema_version TEXT NOT NULL DEFAULT 'bar-v1',
    data_origin TEXT NOT NULL DEFAULT 'sample',
    quality_flags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    raw_payload JSONB,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (index_code, timestamp, source, vendor, source_run_id, import_batch_id),
    CONSTRAINT index_bars_volume_nonnegative CHECK (volume >= 0),
    CONSTRAINT index_bars_high_low CHECK (high >= low),
    CONSTRAINT index_bars_high_open CHECK (high >= open),
    CONSTRAINT index_bars_high_close CHECK (high >= close),
    CONSTRAINT index_bars_low_open CHECK (low <= open),
    CONSTRAINT index_bars_low_close CHECK (low <= close)
);

ALTER TABLE index_bars ADD COLUMN IF NOT EXISTS vendor TEXT NOT NULL DEFAULT 'sample';
ALTER TABLE index_bars ADD COLUMN IF NOT EXISTS source_run_id TEXT NOT NULL DEFAULT 'sample-run';
ALTER TABLE index_bars ADD COLUMN IF NOT EXISTS import_batch_id TEXT NOT NULL DEFAULT 'sample-batch';
ALTER TABLE index_bars ADD COLUMN IF NOT EXISTS schema_version TEXT NOT NULL DEFAULT 'bar-v1';
ALTER TABLE index_bars ADD COLUMN IF NOT EXISTS data_origin TEXT NOT NULL DEFAULT 'sample';
ALTER TABLE index_bars ADD COLUMN IF NOT EXISTS quality_flags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE index_bars ADD COLUMN IF NOT EXISTS raw_payload JSONB;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'index_bars'::regclass
          AND conname = 'index_bars_pkey'
          AND pg_get_constraintdef(oid) = 'PRIMARY KEY (index_code, "timestamp")'
    ) THEN
        ALTER TABLE index_bars DROP CONSTRAINT index_bars_pkey;
        ALTER TABLE index_bars
            ADD CONSTRAINT index_bars_pkey
            PRIMARY KEY (index_code, timestamp, source, vendor, source_run_id, import_batch_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_index_bars_code_timestamp
    ON index_bars (index_code, timestamp);

CREATE INDEX IF NOT EXISTS idx_index_bars_import_batch
    ON index_bars (import_batch_id, source_run_id, source, vendor);

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

CREATE TABLE IF NOT EXISTS trade_runs (
    run_id TEXT PRIMARY KEY,
    trade_mode TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    source_session_id TEXT,
    description TEXT NOT NULL DEFAULT '',
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT trade_runs_run_mode_unique UNIQUE (run_id, trade_mode),
    CONSTRAINT trade_runs_mode_known
        CHECK (trade_mode IN ('dry_run', 'field_shadow', 'paper', 'live')),
    CONSTRAINT trade_runs_time_order
        CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE TABLE IF NOT EXISTS trade_signals (
    signal_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES trade_runs(run_id) ON DELETE CASCADE,
    trade_mode TEXT NOT NULL,
    strategy_group TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    symbol TEXT NOT NULL,
    signal_time TIMESTAMPTZ NOT NULL,
    signal_price NUMERIC(18, 6),
    decision TEXT NOT NULL,
    signal_payload JSONB NOT NULL,
    filter_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    market_snapshot JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT trade_signals_run_mode_fk
        FOREIGN KEY (run_id, trade_mode) REFERENCES trade_runs(run_id, trade_mode) ON DELETE CASCADE,
    CONSTRAINT trade_signals_identity_unique
        UNIQUE (signal_id, run_id, trade_mode, strategy_group),
    CONSTRAINT trade_signals_mode_known
        CHECK (trade_mode IN ('dry_run', 'field_shadow', 'paper', 'live')),
    CONSTRAINT trade_signals_strategy_group_known
        CHECK (strategy_group IN ('day', 'swing')),
    CONSTRAINT trade_signals_decision_known
        CHECK (decision IN ('triggered', 'blocked', 'skipped', 'virtual_order', 'submitted')),
    CONSTRAINT trade_signals_price_positive
        CHECK (signal_price IS NULL OR signal_price > 0)
);

CREATE INDEX IF NOT EXISTS idx_trade_signals_run_strategy
    ON trade_signals (run_id, strategy_group, strategy_id, signal_time);

CREATE INDEX IF NOT EXISTS idx_trade_signals_symbol_time
    ON trade_signals (symbol, signal_time);

CREATE TABLE IF NOT EXISTS trade_orders (
    order_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL REFERENCES trade_signals(signal_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES trade_runs(run_id) ON DELETE CASCADE,
    trade_mode TEXT NOT NULL,
    strategy_group TEXT NOT NULL,
    symbol TEXT NOT NULL,
    order_time TIMESTAMPTZ NOT NULL,
    side TEXT NOT NULL,
    order_status TEXT NOT NULL,
    order_price NUMERIC(18, 6),
    order_quantity NUMERIC(24, 6),
    order_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT trade_orders_signal_context_fk
        FOREIGN KEY (signal_id, run_id, trade_mode, strategy_group)
        REFERENCES trade_signals(signal_id, run_id, trade_mode, strategy_group) ON DELETE CASCADE,
    CONSTRAINT trade_orders_mode_known
        CHECK (trade_mode IN ('dry_run', 'field_shadow', 'paper', 'live')),
    CONSTRAINT trade_orders_strategy_group_known
        CHECK (strategy_group IN ('day', 'swing')),
    CONSTRAINT trade_orders_side_known
        CHECK (side IN ('buy', 'sell')),
    CONSTRAINT trade_orders_status_known
        CHECK (order_status IN ('virtual', 'blocked', 'submitted', 'filled', 'cancelled', 'rejected')),
    CONSTRAINT trade_orders_price_positive
        CHECK (order_price IS NULL OR order_price > 0),
    CONSTRAINT trade_orders_quantity_positive
        CHECK (order_quantity IS NULL OR order_quantity > 0)
);

CREATE TABLE IF NOT EXISTS trade_positions (
    position_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL REFERENCES trade_signals(signal_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES trade_runs(run_id) ON DELETE CASCADE,
    trade_mode TEXT NOT NULL,
    strategy_group TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    symbol TEXT NOT NULL,
    entry_time TIMESTAMPTZ,
    entry_price NUMERIC(18, 6),
    exit_time TIMESTAMPTZ,
    exit_price NUMERIC(18, 6),
    quantity NUMERIC(24, 6),
    pnl NUMERIC(24, 6),
    pnl_rate NUMERIC(18, 8),
    position_status TEXT NOT NULL,
    exit_reason TEXT,
    audit_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT trade_positions_signal_context_fk
        FOREIGN KEY (signal_id, run_id, trade_mode, strategy_group)
        REFERENCES trade_signals(signal_id, run_id, trade_mode, strategy_group) ON DELETE CASCADE,
    CONSTRAINT trade_positions_mode_known
        CHECK (trade_mode IN ('dry_run', 'field_shadow', 'paper', 'live')),
    CONSTRAINT trade_positions_strategy_group_known
        CHECK (strategy_group IN ('day', 'swing')),
    CONSTRAINT trade_positions_status_known
        CHECK (position_status IN ('candidate', 'open', 'closed', 'blocked', 'expired')),
    CONSTRAINT trade_positions_entry_price_positive
        CHECK (entry_price IS NULL OR entry_price > 0),
    CONSTRAINT trade_positions_exit_price_positive
        CHECK (exit_price IS NULL OR exit_price > 0),
    CONSTRAINT trade_positions_quantity_positive
        CHECK (quantity IS NULL OR quantity > 0),
    CONSTRAINT trade_positions_time_order
        CHECK (exit_time IS NULL OR entry_time IS NULL OR exit_time >= entry_time)
);

CREATE INDEX IF NOT EXISTS idx_trade_positions_run_strategy
    ON trade_positions (run_id, strategy_group, strategy_id, symbol);

CREATE TABLE IF NOT EXISTS universe_daily_raw (
    row_id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    trading_date DATE NOT NULL,
    open NUMERIC(18, 6) NOT NULL,
    high NUMERIC(18, 6) NOT NULL,
    low NUMERIC(18, 6) NOT NULL,
    close NUMERIC(18, 6) NOT NULL,
    volume BIGINT,
    value NUMERIC(24, 6),
    data_origin TEXT NOT NULL DEFAULT 'universe-selection-source',
    source TEXT NOT NULL,
    vendor TEXT NOT NULL,
    source_run_id TEXT NOT NULL,
    import_batch_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    quality_flags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    raw_payload JSONB,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT universe_daily_raw_unique_row
        UNIQUE (symbol, trading_date, source, vendor, source_run_id, import_batch_id),
    CONSTRAINT universe_daily_raw_origin CHECK (data_origin = 'universe-selection-source'),
    CONSTRAINT universe_daily_raw_volume_nonnegative CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT universe_daily_raw_value_nonnegative CHECK (value IS NULL OR value >= 0),
    CONSTRAINT universe_daily_raw_high_low CHECK (high >= low),
    CONSTRAINT universe_daily_raw_high_open CHECK (high >= open),
    CONSTRAINT universe_daily_raw_high_close CHECK (high >= close),
    CONSTRAINT universe_daily_raw_low_open CHECK (low <= open),
    CONSTRAINT universe_daily_raw_low_close CHECK (low <= close)
);

CREATE INDEX IF NOT EXISTS idx_universe_daily_raw_symbol_date
    ON universe_daily_raw (symbol, trading_date);

CREATE INDEX IF NOT EXISTS idx_universe_daily_raw_import_batch
    ON universe_daily_raw (import_batch_id);

CREATE TABLE IF NOT EXISTS universe_daily_canonical (
    symbol TEXT NOT NULL,
    trading_date DATE NOT NULL,
    selected_row_id BIGINT NOT NULL REFERENCES universe_daily_raw(row_id) ON DELETE CASCADE,
    open NUMERIC(18, 6) NOT NULL,
    high NUMERIC(18, 6) NOT NULL,
    low NUMERIC(18, 6) NOT NULL,
    close NUMERIC(18, 6) NOT NULL,
    volume BIGINT,
    value NUMERIC(24, 6),
    data_origin TEXT NOT NULL DEFAULT 'universe-selection-source',
    source TEXT NOT NULL,
    vendor TEXT NOT NULL,
    source_run_id TEXT NOT NULL,
    import_batch_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    quality_flags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    raw_payload JSONB,
    source_count INTEGER NOT NULL,
    conflict_flags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, trading_date),
    CONSTRAINT universe_daily_canonical_source_count_positive CHECK (source_count > 0),
    CONSTRAINT universe_daily_canonical_origin CHECK (data_origin = 'universe-selection-source'),
    CONSTRAINT universe_daily_canonical_volume_nonnegative CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT universe_daily_canonical_value_nonnegative CHECK (value IS NULL OR value >= 0),
    CONSTRAINT universe_daily_canonical_high_low CHECK (high >= low),
    CONSTRAINT universe_daily_canonical_high_open CHECK (high >= open),
    CONSTRAINT universe_daily_canonical_high_close CHECK (high >= close),
    CONSTRAINT universe_daily_canonical_low_open CHECK (low <= open),
    CONSTRAINT universe_daily_canonical_low_close CHECK (low <= close)
);

CREATE INDEX IF NOT EXISTS idx_universe_daily_canonical_date
    ON universe_daily_canonical (trading_date);

CREATE TABLE IF NOT EXISTS research_minute_raw (
    row_id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    interval TEXT NOT NULL DEFAULT '1m',
    open NUMERIC(18, 6) NOT NULL,
    high NUMERIC(18, 6) NOT NULL,
    low NUMERIC(18, 6) NOT NULL,
    close NUMERIC(18, 6) NOT NULL,
    volume BIGINT,
    value NUMERIC(24, 6),
    bid_ask_ratio NUMERIC(18, 6),
    traded_value NUMERIC(24, 6),
    action TEXT,
    passed BOOLEAN,
    rank INTEGER,
    reason TEXT,
    score NUMERIC(18, 6),
    strategy_group TEXT,
    input_flags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    data_origin TEXT NOT NULL DEFAULT 'field-observation',
    raw_payload JSONB,
    source TEXT NOT NULL,
    vendor TEXT NOT NULL,
    source_run_id TEXT NOT NULL,
    import_batch_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    quality_flags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT research_minute_raw_unique_row
        UNIQUE (symbol, timestamp, interval, source, vendor, source_run_id, import_batch_id),
    CONSTRAINT research_minute_raw_volume_nonnegative
        CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT research_minute_raw_value_nonnegative
        CHECK (value IS NULL OR value >= 0),
    CONSTRAINT research_minute_raw_bid_ask_ratio_nonnegative
        CHECK (bid_ask_ratio IS NULL OR bid_ask_ratio >= 0),
    CONSTRAINT research_minute_raw_traded_value_nonnegative
        CHECK (traded_value IS NULL OR traded_value >= 0),
    CONSTRAINT research_minute_raw_data_origin_known
        CHECK (data_origin IN ('legacy-minute-backfill', 'field-observation')),
    CONSTRAINT research_minute_raw_origin_interval_pair
        CHECK (
            (data_origin = 'legacy-minute-backfill' AND interval = '1m')
            OR (data_origin = 'field-observation' AND interval = '1m')
        ),
    CONSTRAINT research_minute_raw_high_low
        CHECK (high >= low),
    CONSTRAINT research_minute_raw_high_open
        CHECK (high >= open),
    CONSTRAINT research_minute_raw_high_close
        CHECK (high >= close),
    CONSTRAINT research_minute_raw_low_open
        CHECK (low <= open),
    CONSTRAINT research_minute_raw_low_close
        CHECK (low <= close)
);

CREATE INDEX IF NOT EXISTS idx_research_minute_raw_key
    ON research_minute_raw (symbol, timestamp, interval);

CREATE INDEX IF NOT EXISTS idx_research_minute_raw_timestamp
    ON research_minute_raw (timestamp);

CREATE INDEX IF NOT EXISTS idx_research_minute_raw_import_batch
    ON research_minute_raw (import_batch_id);

CREATE TABLE IF NOT EXISTS research_minute_canonical (
    symbol TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    interval TEXT NOT NULL DEFAULT '1m',
    selected_row_id BIGINT NOT NULL REFERENCES research_minute_raw(row_id) ON DELETE CASCADE,
    open NUMERIC(18, 6) NOT NULL,
    high NUMERIC(18, 6) NOT NULL,
    low NUMERIC(18, 6) NOT NULL,
    close NUMERIC(18, 6) NOT NULL,
    volume BIGINT,
    value NUMERIC(24, 6),
    bid_ask_ratio NUMERIC(18, 6),
    traded_value NUMERIC(24, 6),
    action TEXT,
    passed BOOLEAN,
    rank INTEGER,
    reason TEXT,
    score NUMERIC(18, 6),
    strategy_group TEXT,
    input_flags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    data_origin TEXT NOT NULL DEFAULT 'field-observation',
    raw_payload JSONB,
    source TEXT NOT NULL,
    vendor TEXT NOT NULL,
    source_run_id TEXT NOT NULL,
    import_batch_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    quality_flags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    source_count INTEGER NOT NULL,
    conflict_flags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, timestamp, interval),
    CONSTRAINT research_minute_canonical_source_count_positive CHECK (source_count > 0),
    CONSTRAINT research_minute_canonical_volume_nonnegative
        CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT research_minute_canonical_value_nonnegative
        CHECK (value IS NULL OR value >= 0),
    CONSTRAINT research_minute_canonical_bid_ask_ratio_nonnegative
        CHECK (bid_ask_ratio IS NULL OR bid_ask_ratio >= 0),
    CONSTRAINT research_minute_canonical_traded_value_nonnegative
        CHECK (traded_value IS NULL OR traded_value >= 0),
    CONSTRAINT research_minute_canonical_data_origin_known
        CHECK (data_origin IN ('legacy-minute-backfill', 'field-observation')),
    CONSTRAINT research_minute_canonical_origin_interval_pair
        CHECK (
            (data_origin = 'legacy-minute-backfill' AND interval = '1m')
            OR (data_origin = 'field-observation' AND interval = '1m')
        ),
    CONSTRAINT research_minute_canonical_high_low
        CHECK (high >= low),
    CONSTRAINT research_minute_canonical_high_open
        CHECK (high >= open),
    CONSTRAINT research_minute_canonical_high_close
        CHECK (high >= close),
    CONSTRAINT research_minute_canonical_low_open
        CHECK (low <= open),
    CONSTRAINT research_minute_canonical_low_close
        CHECK (low <= close)
);

CREATE INDEX IF NOT EXISTS idx_research_minute_canonical_timestamp
    ON research_minute_canonical (timestamp);

ALTER TABLE research_minute_raw
    ADD COLUMN IF NOT EXISTS bid_ask_ratio NUMERIC(18, 6),
    ADD COLUMN IF NOT EXISTS traded_value NUMERIC(24, 6),
    ADD COLUMN IF NOT EXISTS action TEXT,
    ADD COLUMN IF NOT EXISTS passed BOOLEAN,
    ADD COLUMN IF NOT EXISTS rank INTEGER,
    ADD COLUMN IF NOT EXISTS reason TEXT,
    ADD COLUMN IF NOT EXISTS score NUMERIC(18, 6),
    ADD COLUMN IF NOT EXISTS strategy_group TEXT,
    ADD COLUMN IF NOT EXISTS input_flags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    ADD COLUMN IF NOT EXISTS data_origin TEXT NOT NULL DEFAULT 'field-observation',
    ADD COLUMN IF NOT EXISTS raw_payload JSONB;

ALTER TABLE research_minute_canonical
    ADD COLUMN IF NOT EXISTS bid_ask_ratio NUMERIC(18, 6),
    ADD COLUMN IF NOT EXISTS traded_value NUMERIC(24, 6),
    ADD COLUMN IF NOT EXISTS action TEXT,
    ADD COLUMN IF NOT EXISTS passed BOOLEAN,
    ADD COLUMN IF NOT EXISTS rank INTEGER,
    ADD COLUMN IF NOT EXISTS reason TEXT,
    ADD COLUMN IF NOT EXISTS score NUMERIC(18, 6),
    ADD COLUMN IF NOT EXISTS strategy_group TEXT,
    ADD COLUMN IF NOT EXISTS input_flags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    ADD COLUMN IF NOT EXISTS data_origin TEXT NOT NULL DEFAULT 'field-observation',
    ADD COLUMN IF NOT EXISTS raw_payload JSONB;

ALTER TABLE research_minute_raw
    ALTER COLUMN data_origin SET DEFAULT 'field-observation';

ALTER TABLE research_minute_canonical
    ALTER COLUMN data_origin SET DEFAULT 'field-observation';

UPDATE research_minute_raw
SET data_origin = CASE
    WHEN lower(source) LIKE 'legacy%' OR lower(vendor) = 'daishin' THEN 'legacy-minute-backfill'
    ELSE 'field-observation'
END
WHERE data_origin = 'unknown' OR data_origin IS NULL;

UPDATE research_minute_canonical
SET data_origin = CASE
    WHEN lower(source) LIKE 'legacy%' OR lower(vendor) = 'daishin' THEN 'legacy-minute-backfill'
    ELSE 'field-observation'
END
WHERE data_origin = 'unknown' OR data_origin IS NULL;

UPDATE research_minute_raw
SET data_origin = 'field-observation',
    interval = '1m',
    quality_flags = array_append(quality_flags, 'minute_table_daily_source_misplaced')
WHERE data_origin = 'universe-selection-source';

UPDATE research_minute_canonical
SET data_origin = 'field-observation',
    interval = '1m',
    quality_flags = array_append(quality_flags, 'minute_table_daily_source_misplaced')
WHERE data_origin = 'universe-selection-source';

DO $$
BEGIN
    ALTER TABLE research_minute_raw
        DROP CONSTRAINT IF EXISTS research_minute_raw_data_origin_known;
    ALTER TABLE research_minute_raw
        DROP CONSTRAINT IF EXISTS research_minute_raw_origin_interval_pair;
    ALTER TABLE research_minute_canonical
        DROP CONSTRAINT IF EXISTS research_minute_canonical_data_origin_known;
    ALTER TABLE research_minute_canonical
        DROP CONSTRAINT IF EXISTS research_minute_canonical_origin_interval_pair;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'research_minute_raw_data_origin_known'
    ) THEN
        ALTER TABLE research_minute_raw
            ADD CONSTRAINT research_minute_raw_data_origin_known
            CHECK (data_origin IN ('legacy-minute-backfill', 'field-observation'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'research_minute_raw_origin_interval_pair'
    ) THEN
        ALTER TABLE research_minute_raw
            ADD CONSTRAINT research_minute_raw_origin_interval_pair
            CHECK (
                (data_origin = 'legacy-minute-backfill' AND interval = '1m')
                OR (data_origin = 'field-observation' AND interval = '1m')
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'research_minute_canonical_data_origin_known'
    ) THEN
        ALTER TABLE research_minute_canonical
            ADD CONSTRAINT research_minute_canonical_data_origin_known
            CHECK (data_origin IN ('legacy-minute-backfill', 'field-observation'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'research_minute_canonical_origin_interval_pair'
    ) THEN
        ALTER TABLE research_minute_canonical
            ADD CONSTRAINT research_minute_canonical_origin_interval_pair
            CHECK (
                (data_origin = 'legacy-minute-backfill' AND interval = '1m')
                OR (data_origin = 'field-observation' AND interval = '1m')
            );
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'trade_runs_run_mode_unique'
    ) THEN
        ALTER TABLE trade_runs
            ADD CONSTRAINT trade_runs_run_mode_unique UNIQUE (run_id, trade_mode);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'trade_signals_run_mode_fk'
    ) THEN
        ALTER TABLE trade_signals
            ADD CONSTRAINT trade_signals_run_mode_fk
            FOREIGN KEY (run_id, trade_mode) REFERENCES trade_runs(run_id, trade_mode) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'trade_signals_identity_unique'
    ) THEN
        ALTER TABLE trade_signals
            ADD CONSTRAINT trade_signals_identity_unique
            UNIQUE (signal_id, run_id, trade_mode, strategy_group);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'trade_orders_signal_context_fk'
    ) THEN
        ALTER TABLE trade_orders
            ADD CONSTRAINT trade_orders_signal_context_fk
            FOREIGN KEY (signal_id, run_id, trade_mode, strategy_group)
            REFERENCES trade_signals(signal_id, run_id, trade_mode, strategy_group) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'trade_positions_signal_context_fk'
    ) THEN
        ALTER TABLE trade_positions
            ADD CONSTRAINT trade_positions_signal_context_fk
            FOREIGN KEY (signal_id, run_id, trade_mode, strategy_group)
            REFERENCES trade_signals(signal_id, run_id, trade_mode, strategy_group) ON DELETE CASCADE;
    END IF;
END $$;
