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
