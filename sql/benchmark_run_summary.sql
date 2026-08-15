-- Raport dla najnowszego runu scripts/benchmark_dialog.py.
-- Session ID ma format: bench-<8 znaków run_id>-<scenario_id>.
-- Jeśli chcesz przeanalizować starszy run, wpisz prefix ręcznie zamiast NULL,
-- np. N'bench-56bef4fd-%'.
DECLARE @session_prefix NVARCHAR(64) = NULL;

IF @session_prefix IS NULL
BEGIN
    DECLARE @latest_benchmark_session NVARCHAR(64);

    SELECT TOP (1)
        @latest_benchmark_session = session_id
    FROM dbo.chat_turn_metrics
    WHERE session_id LIKE N'bench-%'
      AND timing_version >= 1
    ORDER BY created_at DESC, id DESC;

    IF @latest_benchmark_session IS NULL
    BEGIN
        RAISERROR(N'Nie znaleziono żadnych rekordów benchmarku z timing_version >= 1.', 16, 1);
        RETURN;
    END;

    -- "bench-" (5) + run_id (8) + "-" (1) = 14 znaków.
    SET @session_prefix = LEFT(@latest_benchmark_session, 14) + N'%';
END;

SELECT @session_prefix AS benchmark_session_prefix;

-- 1. Wynik każdego scenariusza w wybranym runie.
SELECT
    session_id,
    operation,
    COUNT(*) AS turns,
    SUM(CASE WHEN clarification_required = 1 THEN 1 ELSE 0 END) AS clarification_turns,
    SUM(llm_calls) AS llm_calls,
    SUM(calendar_calls) AS calendar_calls,
    SUM(latency_ms) AS total_ms,
    SUM(llm_latency_ms) AS llm_ms,
    SUM(calendar_latency_ms) AS calendar_ms,
    SUM(backend_latency_ms) AS backend_ms,
    CASE
        WHEN SUM(llm_calls) > 0 AND SUM(calendar_calls) > 0 THEN 'llm+calendar'
        WHEN SUM(llm_calls) > 0 THEN 'llm'
        WHEN SUM(calendar_calls) > 0 THEN 'calendar'
        ELSE 'deterministic'
    END AS execution_path,
    STRING_AGG(status, N' -> ') WITHIN GROUP (ORDER BY created_at) AS status_path
FROM dbo.chat_turn_metrics
WHERE session_id LIKE @session_prefix
  AND timing_version >= 1
GROUP BY session_id, operation
ORDER BY session_id;

-- 2. Zbiorcze porównanie ścieżek wykonania dla tego samego runu.
;WITH benchmark_turns AS (
    SELECT
        *,
        CASE
            WHEN llm_calls > 0 AND calendar_calls > 0 THEN 'llm+calendar'
            WHEN llm_calls > 0 THEN 'llm'
            WHEN calendar_calls > 0 THEN 'calendar'
            ELSE 'deterministic'
        END AS execution_path
    FROM dbo.chat_turn_metrics
    WHERE session_id LIKE @session_prefix
      AND timing_version >= 1
)
SELECT
    execution_path,
    COUNT(*) AS turns,
    CAST(AVG(CAST(latency_ms AS FLOAT)) AS DECIMAL(10,2)) AS avg_total_ms,
    CAST(AVG(CAST(llm_latency_ms AS FLOAT)) AS DECIMAL(10,2)) AS avg_llm_ms,
    CAST(AVG(CAST(calendar_latency_ms AS FLOAT)) AS DECIMAL(10,2)) AS avg_calendar_ms,
    CAST(AVG(CAST(backend_latency_ms AS FLOAT)) AS DECIMAL(10,2)) AS avg_backend_ms,
    SUM(CASE WHEN clarification_required = 1 THEN 1 ELSE 0 END) AS clarification_turns
FROM benchmark_turns
GROUP BY execution_path
ORDER BY execution_path;
GO
