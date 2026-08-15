USE [ai_organizer];
GO

-- Post-event reflections are deliberately separate from conversation_feedback.
-- conversation_feedback evaluates whether the assistant understood a message;
-- event_reflections evaluates the user's experience of a completed activity.
IF OBJECT_ID('dbo.event_reflections', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.event_reflections (
        id BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_event_reflections PRIMARY KEY,
        user_id UNIQUEIDENTIFIER NOT NULL,
        calendar_event_id NVARCHAR(255) NOT NULL,
        event_title NVARCHAR(500) NOT NULL,
        event_start DATETIME2(0) NOT NULL,
        event_end DATETIME2(0) NOT NULL,
        rating TINYINT NULL,
        sentiment NVARCHAR(20) NULL,
        feedback_text NVARCHAR(MAX) NULL,
        worth_repeating BIT NULL,
        created_at DATETIME2(0) NOT NULL CONSTRAINT DF_event_reflections_created_at DEFAULT SYSUTCDATETIME(),
        updated_at DATETIME2(0) NOT NULL CONSTRAINT DF_event_reflections_updated_at DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_event_reflections_user FOREIGN KEY (user_id) REFERENCES dbo.users(id),
        CONSTRAINT UQ_event_reflections_user_calendar_event UNIQUE (user_id, calendar_event_id),
        CONSTRAINT CK_event_reflections_rating CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),
        CONSTRAINT CK_event_reflections_sentiment CHECK (
            sentiment IS NULL OR sentiment IN (N'positive', N'neutral', N'negative', N'mixed')
        ),
        CONSTRAINT CK_event_reflections_time CHECK (event_end >= event_start)
    );

    CREATE INDEX IX_event_reflections_user_end
        ON dbo.event_reflections(user_id, event_end DESC);
END;
GO

IF OBJECT_ID('dbo.motivation_reminders', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.motivation_reminders (
        id BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_motivation_reminders PRIMARY KEY,
        user_id UNIQUEIDENTIFIER NOT NULL,
        reflection_id BIGINT NOT NULL,
        remind_at DATETIME2(0) NOT NULL,
        status NVARCHAR(20) NOT NULL CONSTRAINT DF_motivation_reminders_status DEFAULT N'pending',
        delivered_at DATETIME2(0) NULL,
        completed_at DATETIME2(0) NULL,
        created_at DATETIME2(0) NOT NULL CONSTRAINT DF_motivation_reminders_created_at DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_motivation_reminders_user FOREIGN KEY (user_id) REFERENCES dbo.users(id),
        CONSTRAINT FK_motivation_reminders_reflection FOREIGN KEY (reflection_id) REFERENCES dbo.event_reflections(id),
        CONSTRAINT CK_motivation_reminders_status CHECK (
            status IN (N'pending', N'delivered', N'completed', N'dismissed')
        )
    );

    CREATE INDEX IX_motivation_reminders_due
        ON dbo.motivation_reminders(user_id, status, remind_at);
END;
GO
