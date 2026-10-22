SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF EXISTS (
    SELECT 1
    FROM sys.columns
    WHERE object_id = OBJECT_ID(N'dbo.sessions')
      AND name = N'user_id'
      AND is_nullable = 0
)
BEGIN
    ALTER TABLE dbo.sessions
    ALTER COLUMN user_id int NULL;
END;

COMMIT TRANSACTION;
GO
