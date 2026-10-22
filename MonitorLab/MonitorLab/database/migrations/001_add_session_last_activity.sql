-- LabMonitor: agregar seguimiento de actividad
-- Migracion segura para instalaciones existentes

IF COL_LENGTH('dbo.sessions', 'last_activity_at') IS NULL
BEGIN
    ALTER TABLE dbo.sessions
    ADD last_activity_at DATETIME2 NULL;
END;
GO

UPDATE dbo.sessions
SET last_activity_at = login_at
WHERE logout_at IS NULL
  AND last_activity_at IS NULL;
GO
