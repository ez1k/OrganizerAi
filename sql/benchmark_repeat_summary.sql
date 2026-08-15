-- Statystyki dla batcha utworzonego przez scripts/benchmark_repeat.py.
-- Runner wypisuje np. "SQL run-id prefix: a1b2c%".
-- Wpisz pięć znaków bez %, np. N'a1b2c'. NULL = automatycznie najnowszy batch.
DECLARE @batch_prefix NVARCHAR(5) = NULL;

IF OBJECT_ID('tempdb..#benchmark_runs') IS NOT NULL
    DROP TABLE #benchmark_runs;

IF @batch_prefix IS NULL
BEGIN
    SELECT TOP (1)
        @batch_prefix = LEFT(SUBSTRING(session_id, 7, 8), 5)
    FROM dbo.chat_turn_metrics
    WHERE session_id LIKE N'bench-%'
      AND LEN(session_id) >= 15
      AND timing_version >= 1
    ORDER BY created_at DESC, id DESC;
END;

IF @batch_prefix IS NULL
BEGIN
    RAISERROR(N'Nie znaleziono żadnych rekordów benchmarku.', 16, 1);
    RETURN;
END;

SELECT DISTINCT
    SUBSTRING(session_id, 7, 8) AS run_id
INTO #benchmark_runs
FROM dbo.chat_turn_metrics
WHERE session_id LIKE N'bench-' + @batch_prefix + N'%'
  AND LEN(session_id) >= 15
  AND timing_version >= 1;

SELECT
    @batch_prefix AS benchmark_batch_prefix,
    COUNT(*) AS measured_runs_found,
    MIN(m.created_at) AS first_metric_utc,
    MAX(m.created_at) AS last_metric_utc
FROM #benchmark_runs r
JOIN dbo.chat_turn_metrics m
    ON SUBSTRING(m.session_id, 7, 8) = r.run_id;

-- 1. Statystyki per scenariusz.
-- Dla scenariuszy wieloturowych total_ms jest sumą wszystkich turnów danego scenariusza w runie.
;WITH scenario_runs AS (
    SELECT
        SUBSTRING(m.session_id, 7, 8) AS run_id,
        SUBSTRING(m.session_id, 16, 64) AS scenario,
        MIN(m.operation) AS operation,
        COUNT(*) AS turns,
        SUM(m.latency_ms) AS total_ms,
        SUM(m.llm_latency_ms) AS llm_ms,
        SUM(m.calendar_latency_ms) AS calendar_ms,
        SUM(m.backend_latency_ms) AS backend_ms,
        SUM(m.llm_calls) AS llm_calls,
        SUM(m.calendar_calls) AS calendar_calls,
        SUM(CASE WHEN m.clarification_required = 1 THEN 1 ELSE 0 END) AS clarification_turns
    FROM dbo.chat_turn_metrics m
    JOIN #benchmark_runs r
        ON SUBSTRING(m.session_id, 7, 8) = r.run_id
    WHERE m.timing_version >= 1
    GROUP BY
        SUBSTRING(m.session_id, 7, 8),
        SUBSTRING(m.session_id, 16, 64)
), scenario_stats AS (
    SELECT
        *,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY total_ms)
            OVER (PARTITION BY scenario) AS median_total_ms,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_ms)
            OVER (PARTITION BY scenario) AS p95_total_ms
    FROM scenario_runs
)
SELECT
    scenario,
    MIN(operation) AS operation,
    COUNT(*) AS runs,
    CAST(AVG(CAST(total_ms AS FLOAT)) AS DECIMAL(12,2)) AS avg_total_ms,
    CAST(MAX(median_total_ms) AS DECIMAL(12,2)) AS median_total_ms,
    CAST(MAX(p95_total_ms) AS DECIMAL(12,2)) AS p95_total_ms,
    CAST(STDEV(CAST(total_ms AS FLOAT)) AS DECIMAL(12,2)) AS stddev_total_ms,
    MIN(total_ms) AS min_total_ms,
    MAX(total_ms) AS max_total_ms,
    CAST(AVG(CAST(llm_ms AS FLOAT)) AS DECIMAL(12,2)) AS avg_llm_ms,
    CAST(AVG(CAST(calendar_ms AS FLOAT)) AS DECIMAL(12,2)) AS avg_calendar_ms,
    CAST(AVG(CAST(backend_ms AS FLOAT)) AS DECIMAL(12,2)) AS avg_backend_ms,
    CAST(AVG(CAST(llm_calls AS FLOAT)) AS DECIMAL(10,2)) AS avg_llm_calls,
    CAST(AVG(CAST(calendar_calls AS FLOAT)) AS DECIMAL(10,2)) AS avg_calendar_calls,
    CAST(AVG(CAST(clarification_turns AS FLOAT)) AS DECIMAL(10,2)) AS avg_clarification_turns
FROM scenario_stats
GROUP BY scenario
ORDER BY scenario;

-- 2. Statystyki per ścieżka wykonania dla pojedynczych turnów.
;WITH benchmark_turns AS (
    SELECT
        m.*,
        CASE
            WHEN m.llm_calls > 0 AND m.calendar_calls > 0 THEN 'llm+calendar'
            WHEN m.llm_calls > 0 THEN 'llm'
            WHEN m.calendar_calls > 0 THEN 'calendar'
            ELSE 'deterministic'
        END AS execution_path
    FROM dbo.chat_turn_metrics m
    JOIN #benchmark_runs r
        ON SUBSTRING(m.session_id, 7, 8) = r.run_id
    WHERE m.timing_version >= 1
), path_stats AS (
    SELECT
        *,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY latency_ms)
            OVER (PARTITION BY execution_path) AS median_latency_ms,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)
            OVER (PARTITION BY execution_path) AS p95_latency_ms
    FROM benchmark_turns
)
SELECT
    execution_path,
    COUNT(*) AS turns,
    COUNT(DISTINCT SUBSTRING(session_id, 7, 8)) AS runs,
    CAST(AVG(CAST(latency_ms AS FLOAT)) AS DECIMAL(12,2)) AS avg_latency_ms,
    CAST(MAX(median_latency_ms) AS DECIMAL(12,2)) AS median_latency_ms,
    CAST(MAX(p95_latency_ms) AS DECIMAL(12,2)) AS p95_latency_ms,
    CAST(STDEV(CAST(latency_ms AS FLOAT)) AS DECIMAL(12,2)) AS stddev_latency_ms,
    MIN(latency_ms) AS min_latency_ms,
    MAX(latency_ms) AS max_latency_ms,
    CAST(AVG(CAST(llm_latency_ms AS FLOAT)) AS DECIMAL(12,2)) AS avg_llm_ms,
    CAST(AVG(CAST(calendar_latency_ms AS FLOAT)) AS DECIMAL(12,2)) AS avg_calendar_ms,
    CAST(AVG(CAST(backend_latency_ms AS FLOAT)) AS DECIMAL(12,2)) AS avg_backend_ms
FROM path_stats
GROUP BY execution_path
ORDER BY execution_path;

-- 3. Statystyki per operacja, przydatne do tabeli zbiorczej pracy.
;WITH operation_stats AS (
    SELECT
        m.*,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY latency_ms)
            OVER (PARTITION BY operation) AS median_latency_ms,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)
            OVER (PARTITION BY operation) AS p95_latency_ms
    FROM dbo.chat_turn_metrics m
    JOIN #benchmark_runs r
        ON SUBSTRING(m.session_id, 7, 8) = r.run_id
    WHERE m.timing_version >= 1
)
SELECT
    operation,
    COUNT(*) AS turns,
    CAST(AVG(CAST(latency_ms AS FLOAT)) AS DECIMAL(12,2)) AS avg_latency_ms,
    CAST(MAX(median_latency_ms) AS DECIMAL(12,2)) AS median_latency_ms,
    CAST(MAX(p95_latency_ms) AS DECIMAL(12,2)) AS p95_latency_ms,
    CAST(STDEV(CAST(latency_ms AS FLOAT)) AS DECIMAL(12,2)) AS stddev_latency_ms,
    CAST(100.0 * AVG(CAST(clarification_required AS FLOAT)) AS DECIMAL(8,2)) AS clarification_rate_pct,
    SUM(llm_calls) AS llm_calls,
    SUM(calendar_calls) AS calendar_calls
FROM operation_stats
GROUP BY operation
ORDER BY operation;

DROP TABLE #benchmark_runs;
GO
