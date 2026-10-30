-- SQLite. Daily returns are decimals, not percentages. No forward filling.
CREATE TABLE daily_returns (
  day TEXT PRIMARY KEY,
  market_return REAL NOT NULL CHECK(market_return > -1),
  rf_return REAL NOT NULL CHECK(rf_return > -1)
);
CREATE TABLE event_calendar (
  year INTEGER PRIMARY KEY,
  election_day TEXT NOT NULL,
  is_midterm INTEGER NOT NULL CHECK(is_midterm IN (0,1)),
  six_month_target TEXT NOT NULL,
  twelve_month_target TEXT NOT NULL
);
CREATE TABLE company_financials (
  fiscal_period TEXT PRIMARY KEY,
  revenue_usd_m REAL NOT NULL,
  operating_cash_flow_usd_m REAL NOT NULL,
  cash_capex_usd_m REAL NOT NULL,
  net_income_gaap_usd_m REAL NOT NULL,
  net_income_adjusted_usd_m REAL NOT NULL,
  CHECK(revenue_usd_m > 0 AND operating_cash_flow_usd_m > 0 AND cash_capex_usd_m > 0)
);

CREATE VIEW wealth AS
SELECT day,
 SUM(ln1p(market_return)) OVER(ORDER BY day ROWS UNBOUNDED PRECEDING) AS log_market,
 SUM(ln1p(rf_return)) OVER(ORDER BY day ROWS UNBOUNDED PRECEDING) AS log_cash
FROM daily_returns;

CREATE VIEW boundaries AS
SELECT e.*,
 (SELECT MAX(day) FROM daily_returns WHERE day < election_day) AS entry_day,
 (SELECT MAX(day) FROM daily_returns WHERE day <= printf('%d-12-31',year)) AS year_end,
 (SELECT MAX(day) FROM daily_returns WHERE day <= six_month_target) AS month6_end,
 (SELECT MAX(day) FROM daily_returns WHERE day <= twelve_month_target) AS month12_end
FROM event_calendar e;

CREATE VIEW endpoints AS
SELECT year, is_midterm, election_day, entry_day, year_end AS exit_day, 'year_end' AS horizon FROM boundaries
UNION ALL
SELECT year, is_midterm, election_day, entry_day, month6_end, 'month6' FROM boundaries
UNION ALL
SELECT year, is_midterm, election_day, entry_day, month12_end, 'month12' FROM boundaries;

CREATE VIEW paths AS
SELECT e.*, w.day,
 exp(w.log_market-b.log_market) AS level,
 exp(w.log_cash-b.log_cash) AS cash_level
FROM endpoints e
JOIN wealth b ON b.day=e.entry_day
JOIN wealth w ON w.day BETWEEN e.entry_day AND e.exit_day;

CREATE VIEW running_paths AS
SELECT *, MAX(level) OVER(PARTITION BY year,horizon ORDER BY day ROWS UNBOUNDED PRECEDING) AS running_high
FROM paths;

CREATE VIEW event_results AS
SELECT year,is_midterm,horizon,election_day,entry_day,exit_day,
 MAX(CASE WHEN day=exit_day THEN level-1 END) AS total_return,
 MAX(CASE WHEN day=exit_day THEN cash_level-1 END) AS cash_return,
 MIN(level/running_high-1) AS max_drawdown,
 MIN(level-1) AS worst_from_entry,
 COUNT(*)-1 AS holding_sessions
FROM running_paths
GROUP BY year,is_midterm,horizon,election_day,entry_day,exit_day;

CREATE VIEW company_cash_flow AS
SELECT *,
 operating_cash_flow_usd_m-cash_capex_usd_m AS illustrative_fcf_usd_m,
 cash_capex_usd_m/operating_cash_flow_usd_m AS cash_capex_to_cfo
FROM company_financials;
