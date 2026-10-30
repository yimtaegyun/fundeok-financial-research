-- SQLite window functions. Input grain: (date, series_id), one observation per month.
-- The loaded slice includes 2014 to provide a complete 12-month lag for 2015.
DROP VIEW IF EXISTS monthly_changes;
CREATE VIEW monthly_changes AS
WITH lags AS (
 SELECT date, series_id, value,
        LAG(value,1) OVER w AS lag1,
        LAG(value,3) OVER w AS lag3,
        LAG(value,6) OVER w AS lag6,
        LAG(value,12) OVER w AS lag12
 FROM monthly_observations
 WINDOW w AS (PARTITION BY series_id ORDER BY date)
)
SELECT date,series_id,value,
       CASE WHEN series_id!='PSAVERT' THEN 100.0*(value/lag1-1) END AS mom_pct,
       CASE WHEN series_id!='PSAVERT' THEN 100.0*(value/lag12-1) END AS yoy_pct,
       CASE WHEN series_id!='PSAVERT' THEN 100.0*(POWER(value/lag3,4)-1) END AS annualized_3m_pct,
       CASE WHEN series_id!='PSAVERT' THEN 100.0*(POWER(value/lag6,2)-1) END AS annualized_6m_pct,
       CASE WHEN series_id='PSAVERT' THEN value-lag1 END AS mom_change_pp
FROM lags;

-- Revisions are compared at the same reference period and unit, never treated as new inflation.
DROP VIEW IF EXISTS revision_comparison;
CREATE VIEW revision_comparison AS
SELECT a.metric,a.period,a.unit,a.value AS first_value,b.value AS revised_value,
       b.value-a.value AS revision_pp
FROM release_facts a JOIN release_facts b
 ON a.metric=b.metric AND a.period=b.period AND a.unit=b.unit
WHERE a.published_at='2026-09-30' AND b.published_at='2026-10-29';

-- Use a common observation date for yield decomposition. Missing values are never filled with zero.
DROP VIEW IF EXISTS common_yields;
CREATE VIEW common_yields AS
SELECT date,
 MAX(CASE WHEN series_id='DGS2' THEN value END) AS nominal_2y,
 MAX(CASE WHEN series_id='DGS10' THEN value END) AS nominal_10y,
 MAX(CASE WHEN series_id='DFII10' THEN value END) AS real_10y,
 MAX(CASE WHEN series_id='DGS10' THEN value END)
   - MAX(CASE WHEN series_id='DFII10' THEN value END) AS breakeven_10y
FROM daily_observations GROUP BY date
HAVING COUNT(value)=3;
