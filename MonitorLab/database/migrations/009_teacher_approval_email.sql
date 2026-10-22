-- Apply after migrations 006-008 to enable email-based teacher approval.
SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.teacher_approval_tokens', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.teacher_approval_tokens (
        id INT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_teacher_approval_tokens PRIMARY KEY,
        teacher_user_id INT NOT NULL,
        administrator_user_id INT NOT NULL,
        token_hash CHAR(64) NOT NULL,
        created_at DATETIME2(7) NOT NULL
            CONSTRAINT DF_teacher_approval_token_created
            DEFAULT SYSUTCDATETIME(),
        expires_at DATETIME2(7) NOT NULL,
        consumed_at DATETIME2(7) NULL,
        CONSTRAINT FK_teacher_approval_token_teacher
            FOREIGN KEY (teacher_user_id) REFERENCES dbo.users(id),
        CONSTRAINT FK_teacher_approval_token_admin
            FOREIGN KEY (administrator_user_id) REFERENCES dbo.users(id),
        CONSTRAINT UQ_teacher_approval_token_hash UNIQUE (token_hash)
    );
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.teacher_approval_tokens')
      AND name = N'IX_teacher_approval_tokens_teacher'
)
    CREATE INDEX IX_teacher_approval_tokens_teacher
    ON dbo.teacher_approval_tokens(teacher_user_id, consumed_at, expires_at);
GO

IF OBJECT_ID(N'dbo.teacher_approval_email_notifications', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.teacher_approval_email_notifications (
        id INT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_teacher_approval_email_notifications PRIMARY KEY,
        teacher_user_id INT NOT NULL,
        administrator_user_id INT NOT NULL,
        recipient NVARCHAR(254) NOT NULL,
        subject NVARCHAR(255) NOT NULL,
        body NVARCHAR(MAX) NOT NULL,
        status VARCHAR(20) NOT NULL
            CONSTRAINT DF_teacher_approval_email_status DEFAULT ('pending'),
        attempts INT NOT NULL
            CONSTRAINT DF_teacher_approval_email_attempts DEFAULT (0),
        max_attempts INT NOT NULL
            CONSTRAINT DF_teacher_approval_email_max_attempts DEFAULT (5),
        next_attempt_at DATETIME2(7) NOT NULL
            CONSTRAINT DF_teacher_approval_email_next_attempt
            DEFAULT SYSUTCDATETIME(),
        created_at DATETIME2(7) NOT NULL
            CONSTRAINT DF_teacher_approval_email_created
            DEFAULT SYSUTCDATETIME(),
        sent_at DATETIME2(7) NULL,
        last_error NVARCHAR(1000) NULL,
        CONSTRAINT FK_teacher_approval_email_teacher
            FOREIGN KEY (teacher_user_id) REFERENCES dbo.users(id),
        CONSTRAINT FK_teacher_approval_email_admin
            FOREIGN KEY (administrator_user_id) REFERENCES dbo.users(id),
        CONSTRAINT UQ_teacher_approval_email_admin
            UNIQUE (teacher_user_id, administrator_user_id),
        CONSTRAINT CK_teacher_approval_email_status
            CHECK (status IN ('pending', 'processing', 'sent', 'failed'))
    );
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.teacher_approval_email_notifications')
      AND name = N'IX_teacher_approval_email_pending'
)
    CREATE INDEX IX_teacher_approval_email_pending
    ON dbo.teacher_approval_email_notifications(status, next_attempt_at, id);
GO

COMMIT TRANSACTION;
GO