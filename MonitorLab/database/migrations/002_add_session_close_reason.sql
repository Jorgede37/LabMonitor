-- Add an auditable reason for session closure without changing existing rows.
IF COL_LENGTH('dbo.sessions', 'close_reason') IS NULL
BEGIN
    ALTER TABLE dbo.sessions
    ADD close_reason NVARCHAR(40) NULL;
END;
GO
