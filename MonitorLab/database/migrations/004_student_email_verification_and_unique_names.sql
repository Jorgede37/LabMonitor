-- Apply after migrations 001-003 and before deploying the API changes.
-- Existing duplicate identifiers or lab names must be resolved first.

IF COL_LENGTH(N'dbo.users', N'email_verified') IS NULL
BEGIN
    ALTER TABLE dbo.users
    ADD email_verified BIT NOT NULL
        CONSTRAINT DF_users_email_verified DEFAULT (1);
END;
GO

IF COL_LENGTH(N'dbo.users', N'email_verification_code_hash') IS NULL
BEGIN
    ALTER TABLE dbo.users
    ADD email_verification_code_hash NVARCHAR(64) NULL;
END;
GO

IF COL_LENGTH(N'dbo.users', N'email_verification_expires_at') IS NULL
BEGIN
    ALTER TABLE dbo.users
    ADD email_verification_expires_at DATETIME2(7) NULL;
END;
GO

IF COL_LENGTH(N'dbo.users', N'email_verification_sent_at') IS NULL
BEGIN
    ALTER TABLE dbo.users
    ADD email_verification_sent_at DATETIME2(7) NULL;
END;
GO

IF COL_LENGTH(N'dbo.users', N'email_verification_attempts') IS NULL
BEGIN
    ALTER TABLE dbo.users
    ADD email_verification_attempts INT NOT NULL
        CONSTRAINT DF_users_email_verification_attempts DEFAULT (0);
END;
GO

IF EXISTS (
    SELECT LOWER(LTRIM(RTRIM(username)))
    FROM dbo.users
    GROUP BY LOWER(LTRIM(RTRIM(username)))
    HAVING COUNT(*) > 1
)
BEGIN
    ;THROW 51000, 'Resolve duplicate usernames before applying migration 004.', 1;
END;
GO

IF EXISTS (
    SELECT LOWER(LTRIM(RTRIM(email)))
    FROM dbo.users
    WHERE email IS NOT NULL
    GROUP BY LOWER(LTRIM(RTRIM(email)))
    HAVING COUNT(*) > 1
)
BEGIN
    ;THROW 51001, 'Resolve duplicate email addresses before applying migration 004.', 1;
END;
GO

IF EXISTS (
    SELECT student_id
    FROM dbo.users
    WHERE role = N'student'
      AND student_id IS NOT NULL
    GROUP BY student_id
    HAVING COUNT(*) > 1
)
BEGIN
    ;THROW 51002, 'Resolve duplicate student IDs before applying migration 004.', 1;
END;
GO

IF EXISTS (
    SELECT LOWER(LTRIM(RTRIM(name)))
    FROM dbo.laboratories
    GROUP BY LOWER(LTRIM(RTRIM(name)))
    HAVING COUNT(*) > 1
)
BEGIN
    ;THROW 51003, 'Resolve duplicate laboratory names before applying migration 004.', 1;
END;
GO

IF COL_LENGTH(N'dbo.users', N'username_normalized') IS NULL
BEGIN
    ALTER TABLE dbo.users
    ADD username_normalized AS
        LOWER(LTRIM(RTRIM(username))) PERSISTED;
END;
GO

IF COL_LENGTH(N'dbo.users', N'email_normalized') IS NULL
BEGIN
    ALTER TABLE dbo.users
    ADD email_normalized AS
        CASE
            WHEN email IS NULL THEN NULL
            ELSE LOWER(LTRIM(RTRIM(email)))
        END PERSISTED;
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.users')
      AND name = N'UX_users_username_normalized'
)
BEGIN
    CREATE UNIQUE INDEX UX_users_username_normalized
    ON dbo.users(username_normalized);
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.users')
      AND name = N'UX_users_email_normalized'
)
BEGIN
    CREATE UNIQUE INDEX UX_users_email_normalized
    ON dbo.users(email_normalized)
    WHERE email IS NOT NULL;
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.users')
      AND name = N'UX_users_student_id'
)
BEGIN
    CREATE UNIQUE INDEX UX_users_student_id
    ON dbo.users(student_id)
    WHERE role = N'student' AND student_id IS NOT NULL;
END;
GO

IF COL_LENGTH(N'dbo.laboratories', N'name_normalized') IS NULL
BEGIN
    ALTER TABLE dbo.laboratories
    ADD name_normalized AS
        LOWER(LTRIM(RTRIM(name))) PERSISTED;
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.laboratories')
      AND name = N'UX_laboratories_name_normalized'
)
BEGIN
    CREATE UNIQUE INDEX UX_laboratories_name_normalized
    ON dbo.laboratories(name_normalized);
END;
GO
