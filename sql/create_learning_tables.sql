USE OrganizerAI;
GO

IF OBJECT_ID('dbo.users', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.users (
        id UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_users PRIMARY KEY,
        external_id NVARCHAR(255) NOT NULL,
        created_at DATETIME2(0) NOT NULL CONSTRAINT DF_users_created_at DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_users_external_id UNIQUE (external_id)
    );
END;
GO

IF OBJECT_ID('dbo.learning_examples', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.learning_examples (
        id BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_learning_examples PRIMARY KEY,
        user_id UNIQUEIDENTIFIER NOT NULL,
        message NVARCHAR(MAX) NOT NULL,
        normalized_message NVARCHAR(MAX) NOT NULL,
        result_json NVARCHAR(MAX) NOT NULL,
        corrected BIT NOT NULL CONSTRAINT DF_learning_examples_corrected DEFAULT 0,
        created_at DATETIME2(0) NOT NULL CONSTRAINT DF_learning_examples_created_at DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_learning_examples_user FOREIGN KEY (user_id) REFERENCES dbo.users(id),
        CONSTRAINT CK_learning_examples_result_json CHECK (ISJSON(result_json) = 1)
    );

    CREATE INDEX IX_learning_examples_user_created
        ON dbo.learning_examples(user_id, created_at DESC);
END;
GO

IF OBJECT_ID('dbo.conversation_feedback', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.conversation_feedback (
        id BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_conversation_feedback PRIMARY KEY,
        user_id UNIQUEIDENTIFIER NOT NULL,
        message NVARCHAR(MAX) NOT NULL,
        model_result_json NVARCHAR(MAX) NOT NULL,
        corrected_result_json NVARCHAR(MAX) NULL,
        created_at DATETIME2(0) NOT NULL CONSTRAINT DF_conversation_feedback_created_at DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_conversation_feedback_user FOREIGN KEY (user_id) REFERENCES dbo.users(id),
        CONSTRAINT CK_conversation_feedback_model_json CHECK (ISJSON(model_result_json) = 1),
        CONSTRAINT CK_conversation_feedback_corrected_json CHECK (corrected_result_json IS NULL OR ISJSON(corrected_result_json) = 1)
    );

    CREATE INDEX IX_conversation_feedback_user_created
        ON dbo.conversation_feedback(user_id, created_at DESC);
END;
GO
