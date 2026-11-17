-- ============================================================================
-- Underwriting fraud analytics mart (ANSI SQL; runs on SQLite / Postgres / Snowflake
-- with minor dialect changes). Loaded by run_pipeline.py from the synthetic dataset.
-- ============================================================================

-- One row per application reaching the fraud decision step of the LOS
CREATE TABLE IF NOT EXISTS applications (
    app_id                    TEXT PRIMARY KEY,
    app_date                  DATE NOT NULL,
    app_month                 TEXT NOT NULL,
    dealer_id                 TEXT NOT NULL,
    dealer_state              TEXT,
    applicant_age             INTEGER,
    credit_file_type          TEXT CHECK (credit_file_type IN ('thick','thin','no_file')),
    ssn_issue_age             REAL,
    phone_tenure_days         INTEGER,
    email_tenure_days         INTEGER,
    address_type              TEXT,
    bureau_score              REAL,
    au_tradelines             INTEGER,
    oldest_tradeline_months   INTEGER,
    inquiries_6m              INTEGER,
    stated_income_monthly     REAL,
    verified_income_monthly   REAL,
    income_ratio              REAL,
    employer_verified         INTEGER,
    vehicle_price             REAL,
    amount_financed           REAL,
    ltv                       REAL,
    pti                       REAL,
    dist_to_dealer_km         REAL,
    device_apps_30d           INTEGER,
    ssn_apps_30d              INTEGER,
    phone_shared_count        INTEGER,
    dealer_rapid_resubmits    INTEGER
);

-- Third-party vendor responses (one row per app x vendor call)
CREATE TABLE IF NOT EXISTS vendor_responses (
    app_id        TEXT NOT NULL REFERENCES applications(app_id),
    vendor        TEXT NOT NULL,      -- A_IDV, B_SYNTH, C_DEVICE, D_INCOME, E_CONSORTIUM
    risk_score    REAL,               -- normalised 0-1000 (D: probability x 1000)
    PRIMARY KEY (app_id, vendor)
);

-- Fraud decision produced by the LOS decision engine (champion = production, challenger = shadow)
CREATE TABLE IF NOT EXISTS fraud_decisions (
    app_id        TEXT NOT NULL REFERENCES applications(app_id),
    strategy      TEXT NOT NULL CHECK (strategy IN ('champion','challenger')),
    decision      TEXT NOT NULL CHECK (decision IN ('APPROVE','STIP','REVIEW','DECLINE')),
    ml_score      REAL,
    reason_codes  TEXT,
    PRIMARY KEY (app_id, strategy)
);

-- Confirmed outcomes (investigations, FPD, charge-off), joined back for performance
CREATE TABLE IF NOT EXISTS fraud_outcomes (
    app_id                 TEXT PRIMARY KEY REFERENCES applications(app_id),
    is_fraud               INTEGER NOT NULL,
    fraud_type             TEXT,
    first_payment_default  INTEGER,
    loss_if_funded         REAL
);

CREATE INDEX IF NOT EXISTS ix_app_month  ON applications(app_month);
CREATE INDEX IF NOT EXISTS ix_app_dealer ON applications(dealer_id);
CREATE INDEX IF NOT EXISTS ix_dec_strat  ON fraud_decisions(strategy, decision);
