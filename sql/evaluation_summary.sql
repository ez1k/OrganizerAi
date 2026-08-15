-- 1. Wydajność i odsetek doprecyzowań per operacja.
WITH measured AS (
    SELECT
        operation,
        latency_ms,
        clarification_required,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)
            OVER (PARTITION BY operation) AS p95_latency_ms
    FROM dbo.chat_turn_metrics
)
SELECT
    operation,
    COUNT(*) AS turns,
    CAST(AVG(CAST(latency_ms AS FLOAT)) AS DECIMAL(10,2)) AS avg_latency_ms,
    CAST(MAX(p95_latency_ms) AS DECIMAL(10,2)) AS p95_latency_ms,
    MIN(latency_ms) AS min_latency_ms,
    MAX(latency_ms) AS max_latency_ms,
    CAST(100.0 * AVG(CAST(clarification_required AS FLOAT)) AS DECIMAL(6,2))
        AS clarification_rate_pct
FROM measured
GROUP BY operation
ORDER BY operation;
GO

-- 2. Przebieg sesji: liczba turnów, doprecyzowań i wynik końcowy.
SELECT
    session_id,
    MIN(created_at) AS started_at_utc,
    MAX(created_at) AS finished_at_utc,
    COUNT(*) AS turns,
    SUM(CASE WHEN clarification_required = 1 THEN 1 ELSE 0 END) AS clarification_turns,
    MAX(CASE WHEN status IN ('confirmed', 'deleted', 'calendar_search') THEN 1 ELSE 0 END)
        AS reached_success_state,
    MAX(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS had_error
FROM dbo.chat_turn_metrics
GROUP BY session_id
ORDER BY started_at_utc DESC;
GO

-- 3. Jakość interpretacji z istniejącego feedbacku.
-- accepted_first_pass: użytkownik zaakceptował pierwotny wynik bez korekty.
-- corrected_after_rejection: wynik został później poprawiony.
SELECT
    COUNT(*) AS feedback_rows,
    SUM(CASE
        WHEN corrected_result_json IS NOT NULL
         AND corrected_result_json = model_result_json THEN 1 ELSE 0 END) AS accepted_first_pass,
    SUM(CASE
        WHEN corrected_result_json IS NOT NULL
         AND corrected_result_json <> model_result_json THEN 1 ELSE 0 END) AS corrected_after_rejection,
    SUM(CASE WHEN corrected_result_json IS NULL THEN 1 ELSE 0 END) AS awaiting_correction,
    CAST(
        100.0 * SUM(CASE
            WHEN corrected_result_json IS NOT NULL
             AND corrected_result_json = model_result_json THEN 1 ELSE 0 END)
        / NULLIF(COUNT(*), 0)
        AS DECIMAL(6,2)
    ) AS first_pass_acceptance_pct
FROM dbo.conversation_feedback;
GO
