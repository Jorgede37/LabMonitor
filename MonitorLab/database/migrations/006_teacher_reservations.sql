-- Apply after migrations 001-005, before deploying the API changes.
SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF COL_LENGTH(N'dbo.users', N'teacher_id') IS NULL
    ALTER TABLE dbo.users ADD teacher_id NVARCHAR(50) NULL;
GO

IF COL_LENGTH(N'dbo.users', N'teacher_approved') IS NULL
    ALTER TABLE dbo.users ADD teacher_approved BIT NOT NULL
        CONSTRAINT DF_users_teacher_approved DEFAULT (0);
GO

IF COL_LENGTH(N'dbo.users', N'teacher_approved_by') IS NULL
    ALTER TABLE dbo.users ADD teacher_approved_by INT NULL;
GO

IF COL_LENGTH(N'dbo.users', N'teacher_approved_at') IS NULL
    ALTER TABLE dbo.users ADD teacher_approved_at DATETIME2(7) NULL;
GO

IF EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID(N'dbo.users')
      AND name = N'CK_users_role'
)
    ALTER TABLE dbo.users DROP CONSTRAINT CK_users_role;
GO

ALTER TABLE dbo.users WITH CHECK
ADD CONSTRAINT CK_users_role
CHECK (role IN (N'admin', N'student', N'teacher'));

IF NOT EXISTS (
    SELECT 1 FROM sys.foreign_keys
    WHERE name = N'FK_users_teacher_approved_by'
)
    ALTER TABLE dbo.users WITH CHECK
    ADD CONSTRAINT FK_users_teacher_approved_by
    FOREIGN KEY (teacher_approved_by) REFERENCES dbo.users(id);

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.users')
      AND name = N'UX_users_teacher_id'
)
    CREATE UNIQUE INDEX UX_users_teacher_id
    ON dbo.users(teacher_id)
    WHERE role = N'teacher' AND teacher_id IS NOT NULL;

IF OBJECT_ID(N'dbo.lab_reservations', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.lab_reservations (
        id INT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_lab_reservations PRIMARY KEY,
        teacher_user_id INT NOT NULL,
        reservation_date DATE NOT NULL,
        start_time TIME(0) NOT NULL,
        end_time TIME(0) NOT NULL,
        subject NVARCHAR(150) NOT NULL,
        created_at DATETIME2(7) NOT NULL
            CONSTRAINT DF_lab_reservations_created_at
            DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_lab_reservations_teacher
            FOREIGN KEY (teacher_user_id) REFERENCES dbo.users(id),
        CONSTRAINT CK_lab_reservations_hour
            CHECK (
                start_time >= '07:00'
                AND start_time < '16:00'
                AND DATEPART(MINUTE, start_time) = 0
                AND DATEPART(SECOND, start_time) = 0
                AND end_time > start_time
                AND DATEDIFF(MINUTE, start_time, end_time) % 60 = 0
                AND DATEPART(MINUTE, end_time) = 0
                AND DATEPART(SECOND, end_time) = 0
                AND end_time <= '16:00'
            )
    );
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.lab_reservations')
      AND name = N'UX_lab_reservations_slot'
)
    CREATE UNIQUE INDEX UX_lab_reservations_slot
    ON dbo.lab_reservations(reservation_date, start_time);

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.lab_reservations')
      AND name = N'IX_lab_reservations_teacher_date'
)
    CREATE INDEX IX_lab_reservations_teacher_date
    ON dbo.lab_reservations(teacher_user_id, reservation_date, start_time);

IF OBJECT_ID(N'dbo.reservation_email_notifications', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.reservation_email_notifications (
        id INT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_reservation_email_notifications PRIMARY KEY,
        reservation_id INT NOT NULL,
        recipient NVARCHAR(254) NOT NULL,
        subject NVARCHAR(255) NOT NULL,
        body NVARCHAR(MAX) NOT NULL,
        status VARCHAR(20) NOT NULL
            CONSTRAINT DF_reservation_email_status DEFAULT ('pending'),
        attempts INT NOT NULL
            CONSTRAINT DF_reservation_email_attempts DEFAULT (0),
        max_attempts INT NOT NULL
            CONSTRAINT DF_reservation_email_max_attempts DEFAULT (5),
        next_attempt_at DATETIME2(7) NOT NULL
            CONSTRAINT DF_reservation_email_next_attempt
            DEFAULT SYSUTCDATETIME(),
        created_at DATETIME2(7) NOT NULL
            CONSTRAINT DF_reservation_email_created_at
            DEFAULT SYSUTCDATETIME(),
        sent_at DATETIME2(7) NULL,
        last_error NVARCHAR(1000) NULL,
        CONSTRAINT FK_reservation_email_reservation
            FOREIGN KEY (reservation_id)
            REFERENCES dbo.lab_reservations(id),
        CONSTRAINT UQ_reservation_email_recipient
            UNIQUE (reservation_id, recipient),
        CONSTRAINT CK_reservation_email_status
            CHECK (status IN ('pending', 'processing', 'sent', 'failed'))
    );
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.reservation_email_notifications')
      AND name = N'IX_reservation_email_pending'
)
    CREATE INDEX IX_reservation_email_pending
    ON dbo.reservation_email_notifications(status, next_attempt_at, id);

COMMIT TRANSACTION;
GO