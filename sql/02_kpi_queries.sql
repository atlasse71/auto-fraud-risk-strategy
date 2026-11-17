-- ============================================================================
-- Underwriting fraud KPI & investigation queries.
-- Each query is named with "-- name: <id>" so run_pipeline.py can execute and
-- export it (outputs/sql_<id>.csv). All are validated against the synthetic mart.
-- ============================================================================

-- name: monthly_kpis
-- Executive KPI pack by month and strategy: auto-approval, review rate, capture, FPR, residual loss
WITH d AS (
    SELECT a.app_month, f.strategy, f.decision, o.is_fraud, o.loss_if_funded, a.amount_financed
    FROM fraud_decisions f
    JOIN applications   a ON a.app_id = f.app_id
    JOIN fraud_outcomes o ON o.app_id = f.app_id
)
SELECT app_month,
       strategy,
       COUNT(*)                                                                AS applications,
       ROUND(AVG(CASE WHEN decision = 'APPROVE' THEN 1.0 ELSE 0 END), 4)       AS auto_approval_rate,
       ROUND(AVG(CASE WHEN decision = 'REVIEW'  THEN 1.0 ELSE 0 END), 4)       AS manual_review_rate,
       SUM(CASE WHEN decision = 'REVIEW' THEN 1 ELSE 0 END)                    AS review_queue_volume,
       ROUND(1.0 * SUM(CASE WHEN is_fraud = 1 AND decision <> 'APPROVE' THEN 1 ELSE 0 END)
             / NULLIF(SUM(is_fraud), 0), 4)                                    AS fraud_flag_rate,
       ROUND(1.0 * SUM(CASE WHEN is_fraud = 0 AND decision <> 'APPROVE' THEN 1 ELSE 0 END)
             / NULLIF(SUM(1 - is_fraud), 0), 4)                                AS false_positive_rate,
       ROUND(1.0 * SUM(CASE WHEN decision = 'REVIEW' AND is_fraud = 1 THEN 1 ELSE 0 END)
             / NULLIF(SUM(CASE WHEN decision = 'REVIEW' THEN 1 ELSE 0 END), 0), 4) AS review_hit_rate,
       ROUND(SUM(CASE WHEN is_fraud = 1 AND decision = 'APPROVE' THEN loss_if_funded ELSE 0 END), 0)
                                                                               AS unflagged_fraud_loss_usd,
       ROUND(1e4 * SUM(CASE WHEN is_fraud = 1 AND decision = 'APPROVE' THEN loss_if_funded ELSE 0 END)
             / SUM(amount_financed), 1)                                        AS unflagged_loss_bps
FROM d
GROUP BY app_month, strategy
ORDER BY app_month, strategy;

-- name: synthetic_identity_candidates
-- Synthetic-ID investigation list: piggy-backed AU lines, adult-issued SSN, new contact data,
-- shared phone across identities. Ranked by vendor B synthetic score.
SELECT a.app_id, a.app_date, a.dealer_id, a.applicant_age, a.ssn_issue_age,
       a.au_tradelines, a.oldest_tradeline_months, a.phone_tenure_days, a.phone_shared_count,
       v.risk_score AS synth_score, o.fraud_type
FROM applications a
JOIN vendor_responses v ON v.app_id = a.app_id AND v.vendor = 'B_SYNTH'
JOIN fraud_outcomes   o ON o.app_id = a.app_id
WHERE a.au_tradelines >= 3
  AND a.oldest_tradeline_months < 60
  AND (a.phone_tenure_days < 180 OR a.phone_shared_count >= 2)
ORDER BY v.risk_score DESC
LIMIT 200;

-- name: phone_identity_rings
-- Link analysis: phones shared by multiple identities within the same dealer cluster
SELECT a.dealer_id,
       COUNT(*)                              AS apps_with_shared_phone,
       SUM(o.is_fraud)                       AS confirmed_fraud,
       ROUND(AVG(o.is_fraud), 3)             AS fraud_rate,
       ROUND(SUM(o.loss_if_funded * o.is_fraud), 0) AS exposure_usd
FROM applications a
JOIN fraud_outcomes o ON o.app_id = a.app_id
WHERE a.phone_shared_count >= 2
GROUP BY a.dealer_id
HAVING COUNT(*) >= 3
ORDER BY confirmed_fraud DESC, exposure_usd DESC
LIMIT 25;

-- name: straw_buyer_dealer_concentration
-- Straw-buyer / dealer-collusion screen: dealers whose buyers travel far for high-value units,
-- with repeated re-submissions. Compares each dealer to the portfolio with a z-score.
WITH portfolio AS (SELECT AVG(is_fraud) AS p FROM fraud_outcomes),
dealer AS (
    SELECT a.dealer_id, a.dealer_state,
           COUNT(*)                                             AS apps,
           SUM(o.is_fraud)                                      AS fraud,
           SUM(CASE WHEN o.fraud_type = 'straw_buyer' THEN 1 ELSE 0 END) AS straw,
           AVG(a.dist_to_dealer_km)                             AS avg_dist_km,
           AVG(a.vehicle_price)                                 AS avg_price,
           AVG(a.dealer_rapid_resubmits)                        AS avg_resubmits
    FROM applications a JOIN fraud_outcomes o ON o.app_id = a.app_id
    GROUP BY a.dealer_id, a.dealer_state
    HAVING COUNT(*) >= 40
)
SELECT d.*, ROUND(1.0 * d.fraud / d.apps, 4) AS fraud_rate,
       ROUND((d.fraud - d.apps * p.p) / SQRT(d.apps * p.p * (1 - p.p)), 2) AS z_score
FROM dealer d CROSS JOIN portfolio p
ORDER BY z_score DESC
LIMIT 25;

-- name: income_misrep_by_file_type
-- Income misrepresentation: stated vs bank-verified income gap by credit file depth
SELECT a.credit_file_type,
       COUNT(*)                                                         AS bank_linked_apps,
       ROUND(AVG(a.income_ratio), 3)                                    AS avg_stated_to_verified,
       ROUND(AVG(CASE WHEN a.income_ratio > 1.35 THEN 1.0 ELSE 0 END), 4) AS share_gt_135pct,
       ROUND(AVG(CASE WHEN a.income_ratio > 1.35 THEN o.is_fraud END), 4) AS fraud_rate_when_gt_135pct,
       ROUND(AVG(CASE WHEN a.income_ratio <= 1.35 THEN o.is_fraud END), 4) AS fraud_rate_otherwise
FROM applications a JOIN fraud_outcomes o ON o.app_id = a.app_id
WHERE a.verified_income_monthly IS NOT NULL
GROUP BY a.credit_file_type
ORDER BY a.credit_file_type;

-- name: vendor_decile_lift
-- Vendor signal lift by decile (rank-ordering check used in vendor reviews)
WITH ranked AS (
    SELECT v.vendor, v.risk_score, o.is_fraud,
           NTILE(10) OVER (PARTITION BY v.vendor ORDER BY v.risk_score DESC) AS decile
    FROM vendor_responses v JOIN fraud_outcomes o ON o.app_id = v.app_id
    WHERE v.risk_score IS NOT NULL
)
SELECT vendor, decile, COUNT(*) AS apps,
       ROUND(AVG(is_fraud), 4) AS fraud_rate,
       ROUND(AVG(is_fraud) / (SELECT AVG(is_fraud) FROM fraud_outcomes), 2) AS lift
FROM ranked
GROUP BY vendor, decile
ORDER BY vendor, decile;

-- name: review_queue_sla
-- Daily manual review queue vs analyst capacity (2 analysts x 17 reviews/day = 34)
SELECT a.app_date,
       SUM(CASE WHEN f.decision = 'REVIEW' THEN 1 ELSE 0 END) AS review_volume,
       34                                                    AS daily_capacity,
       CASE WHEN SUM(CASE WHEN f.decision = 'REVIEW' THEN 1 ELSE 0 END) > 34
            THEN 'OVER CAPACITY' ELSE 'OK' END                 AS status
FROM fraud_decisions f JOIN applications a ON a.app_id = f.app_id
WHERE f.strategy = 'challenger'
GROUP BY a.app_date
ORDER BY review_volume DESC
LIMIT 15;

-- name: reason_code_effectiveness
-- Which reason codes are driving reviews, and how productive is each (precision)?
WITH RECURSIVE split(app_id, strategy, code, rest) AS (
    SELECT app_id, strategy, '', reason_codes || ';' FROM fraud_decisions
    WHERE strategy = 'challenger' AND reason_codes <> ''
    UNION ALL
    SELECT app_id, strategy, substr(rest, 1, instr(rest, ';') - 1), substr(rest, instr(rest, ';') + 1)
    FROM split WHERE rest <> ''
)
SELECT s.code AS reason_code, COUNT(*) AS fires, SUM(o.is_fraud) AS confirmed_fraud,
       ROUND(AVG(o.is_fraud), 4) AS precision
FROM split s JOIN fraud_outcomes o ON o.app_id = s.app_id
WHERE s.code <> ''
GROUP BY s.code
ORDER BY confirmed_fraud DESC;
