IF OBJECT_ID('dbo.chat_turn_metrics', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.chat_turn_metrics (
        id BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_chat_turn_metrics PRIMARY KEY,
        user_id UNIQUEIDENTIFIER NOT NULL,
        session_id NVARCHAR(64) NOT NULL,
        operation NVARCHAR(32) NOT NULL,
        status NVARCHAR(64) NOT NULL,
        latency_ms INT NOT NULL,
        llm_latency_ms INT NOT NULL CONSTRAINT DF_chat_turn_metrics_llm_latency DEFAULT 0,
        calendar_latency_ms INT NOT NULL CONSTRAINT DF_chat_turn_metrics_calendar_latency DEFAULT 0,
        backend_latency_ms INT NOT NULL CONSTRAINT DF_chat_turn_metrics_backend_latency DEFAULT 0,
        llm_calls INT NOT NULL CONSTRAINT DF_chat_turn_metrics_llm_calls DEFAULT 0,
        calendar_calls INT NOT NULL CONSTRAINT DF_chat_turn_metrics_calendar_calls DEFAULT 0,
        clarification_required BIT NOT NULL,
        had_draft BIT NOT NULL,
        message_length INT NOT NULL,
        created_at DATETIME2(3) NOT NULL CONSTRAINT DF_chat_turn_metrics_created_at DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_chat_turn_metrics_user FOREIGN KEY (user_id) REFERENCES dbo.users(id),
        CONSTRAINT CK_chat_turn_metrics_latency CHECK (latency_ms >= 0),
        CONSTRAINT CK_chat_turn_metrics_llm_latency CHECK (llm_latency_ms >= 0),
        CONSTRAINT CK_chat_turn_metrics_calendar_latency CHECK (calendar_latency_ms >= 0),
        CONSTRAINT CK_chat_turn_metrics_backend_latency CHECK (backend_latency_ms >= 0),
        CONSTRAINT CK_chat_turn_metrics_llm_calls CHECK (llm_calls >= 0),
        CONSTRAINT CK_chat_turn_metrics_calendar_calls CHECK (calendar_calls >= 0),
        CONSTRAINT CK_chat_turn_metrics_message_length CHECK (message_length >= 0)
    );

    CREATE INDEX IX_chat_turn_metrics_user_created
        ON dbo.chat_turn_metrics(user_id, created_at DESC);

    CREATE INDEX IX_chat_turn_metrics_session_created
        ON dbo.chat_turn_metrics(session_id, created_at ASC);
END;
GO

-- Idempotent upgrade path for installations that already have chat_turn_metrics.
IF COL_LENGTH('dbo.chat_turn_metrics', 'llm_latency_ms') IS NULL
BEGIN
    ALTER TABLE dbo.chat_turn_metrics
        ADD llm_latency_ms INT NOT NULL
            CONSTRAINT DF_chat_turn_metrics_llm_latency DEFAULT 0 WITH VALUES;
END;
GO

IF COL_LENGTH('dbo.chat_turn_metrics', 'calendar_latency_ms') IS NULL
BEGIN
    ALTER TABLE dbo.chat_turn_metrics
        ADD calendar_latency_ms INT NOT NULL
            CONSTRAINT DF_chat_turn_metrics_calendar_latency DEFAULT 0 WITH VALUES;
END;
GO

IF COL_LENGTH('dbo.chat_turn_metrics', 'backend_latency_ms') IS NULL
BEGIN
    ALTER TABLE dbo.chat_turn_metrics
        ADD backend_latency_ms INT NOT NULL
            CONSTRAINT DF_chat_turn_metrics_backend_latency DEFAULT 0 WITH VALUES;
END;
GO

IF COL_LENGTH('dbo.chat_turn_metrics', 'llm_calls') IS NULL
BEGIN
    ALTER TABLE dbo.chat_turn_metrics
        ADD llm_calls INT NOT NULL
            CONSTRAINT DF_chat_turn_metrics_llm_calls DEFAULT 0 WITH VALUES;
END;
GO

IF COL_LENGTH('dbo.chat_turn_metrics', 'calendar_calls') IS NULL
BEGIN
    ALTER TABLE dbo.chat_turn_metrics
        ADD calendar_calls INT NOT NULL
            CONSTRAINT DF_chat_turn_metrics_calendar_calls DEFAULT 0 WITH VALUES;
END;
GO
