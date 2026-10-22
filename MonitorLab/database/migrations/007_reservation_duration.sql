-- Apply after migration 006 to allow contiguous reservations longer than one hour.
SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID(N'dbo.lab_reservations')
      AND name = N'CK_lab_reservations_hour'
)
    ALTER TABLE dbo.lab_reservations
    DROP CONSTRAINT CK_lab_reservations_hour;
GO

ALTER TABLE dbo.lab_reservations WITH CHECK
ADD CONSTRAINT CK_lab_reservations_hour
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
);
GO

COMMIT TRANSACTION;
GO