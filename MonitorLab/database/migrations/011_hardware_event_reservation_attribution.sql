-- Apply after migration 010 to snapshot the reservation context for each
-- newly recorded hardware event.
SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF COL_LENGTH(N'dbo.hardware_events', N'reservation_id') IS NULL
    ALTER TABLE dbo.hardware_events ADD reservation_id INT NULL;

IF COL_LENGTH(N'dbo.hardware_events', N'reserved_teacher_user_id') IS NULL
    ALTER TABLE dbo.hardware_events ADD reserved_teacher_user_id INT NULL;

IF COL_LENGTH(N'dbo.hardware_events', N'reserved_teacher_name') IS NULL
    ALTER TABLE dbo.hardware_events ADD reserved_teacher_name NVARCHAR(150) NULL;

IF COL_LENGTH(N'dbo.hardware_events', N'reserved_teacher_matricula') IS NULL
    ALTER TABLE dbo.hardware_events ADD reserved_teacher_matricula NVARCHAR(50) NULL;

IF COL_LENGTH(N'dbo.hardware_events', N'reservation_subject') IS NULL
    ALTER TABLE dbo.hardware_events ADD reservation_subject NVARCHAR(150) NULL;

IF COL_LENGTH(N'dbo.hardware_events', N'reservation_was_active') IS NULL
    ALTER TABLE dbo.hardware_events ADD reservation_was_active BIT NULL;

COMMIT TRANSACTION;
