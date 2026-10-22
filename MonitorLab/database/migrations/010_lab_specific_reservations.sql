-- Apply after migration 009 to separate reservations by laboratory.
SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF COL_LENGTH(N'dbo.lab_reservations', N'laboratory_id') IS NULL
    ALTER TABLE dbo.lab_reservations
    ADD laboratory_id INT NULL;
GO

IF NOT EXISTS (
    SELECT 1
    FROM dbo.laboratories
    WHERE LOWER(LTRIM(RTRIM(name))) = N'laboratorio principal'
)
    INSERT INTO dbo.laboratories (name)
    VALUES (N'Laboratorio principal');
GO

UPDATE dbo.lab_reservations
SET laboratory_id = (
    SELECT TOP (1) id
    FROM dbo.laboratories
    WHERE LOWER(LTRIM(RTRIM(name))) = N'laboratorio principal'
    ORDER BY id
)
WHERE laboratory_id IS NULL;
GO

ALTER TABLE dbo.lab_reservations
ALTER COLUMN laboratory_id INT NOT NULL;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.foreign_keys
    WHERE name = N'FK_lab_reservations_laboratory'
)
    ALTER TABLE dbo.lab_reservations WITH CHECK
    ADD CONSTRAINT FK_lab_reservations_laboratory
    FOREIGN KEY (laboratory_id) REFERENCES dbo.laboratories(id);
GO

IF EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.lab_reservations')
      AND name = N'UX_lab_reservations_slot'
)
    DROP INDEX UX_lab_reservations_slot
    ON dbo.lab_reservations;
GO

CREATE UNIQUE INDEX UX_lab_reservations_slot
ON dbo.lab_reservations(laboratory_id, reservation_date, start_time)
WHERE status = 'confirmed';
GO

COMMIT TRANSACTION;
GO
