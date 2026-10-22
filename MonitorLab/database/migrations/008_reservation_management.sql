-- Apply after migrations 006 and 007 to enable reservation management and audit.
SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF COL_LENGTH(N'dbo.lab_reservations', N'status') IS NULL
    ALTER TABLE dbo.lab_reservations ADD status VARCHAR(20) NOT NULL
        CONSTRAINT DF_lab_reservations_status DEFAULT ('confirmed') WITH VALUES;
GO

IF COL_LENGTH(N'dbo.lab_reservations', N'created_by_user_id') IS NULL
    ALTER TABLE dbo.lab_reservations ADD created_by_user_id INT NULL;
GO

UPDATE dbo.lab_reservations
SET created_by_user_id = teacher_user_id
WHERE created_by_user_id IS NULL;
GO

IF COL_LENGTH(N'dbo.lab_reservations', N'updated_at') IS NULL
    ALTER TABLE dbo.lab_reservations ADD updated_at DATETIME2(7) NULL;
GO

IF COL_LENGTH(N'dbo.lab_reservations', N'updated_by_user_id') IS NULL
    ALTER TABLE dbo.lab_reservations ADD updated_by_user_id INT NULL;
GO

IF EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.lab_reservations')
      AND name = N'UX_lab_reservations_slot'
)
    DROP INDEX UX_lab_reservations_slot ON dbo.lab_reservations;
GO

CREATE UNIQUE INDEX UX_lab_reservations_slot
ON dbo.lab_reservations(reservation_date, start_time)
WHERE status = 'confirmed';
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID(N'dbo.lab_reservations')
      AND name = N'CK_lab_reservations_status'
)
    ALTER TABLE dbo.lab_reservations WITH CHECK
    ADD CONSTRAINT CK_lab_reservations_status
    CHECK (status IN ('confirmed', 'cancelled'));
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.foreign_keys
    WHERE name = N'FK_lab_reservations_created_by'
)
    ALTER TABLE dbo.lab_reservations WITH CHECK
    ADD CONSTRAINT FK_lab_reservations_created_by
    FOREIGN KEY (created_by_user_id) REFERENCES dbo.users(id);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.foreign_keys
    WHERE name = N'FK_lab_reservations_updated_by'
)
    ALTER TABLE dbo.lab_reservations WITH CHECK
    ADD CONSTRAINT FK_lab_reservations_updated_by
    FOREIGN KEY (updated_by_user_id) REFERENCES dbo.users(id);
GO

COMMIT TRANSACTION;
GO