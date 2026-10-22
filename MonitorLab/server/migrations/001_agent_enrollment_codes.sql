IF OBJECT_ID(N'dbo.agent_enrollment_codes', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.agent_enrollment_codes (
        code_hash CHAR(64) NOT NULL,
        created_by INT NOT NULL,
        created_at DATETIME2(7) NOT NULL
            CONSTRAINT DF_agent_enrollment_codes_created_at DEFAULT (SYSDATETIME()),
        expires_at DATETIME2(7) NOT NULL,
        consumed_at DATETIME2(7) NULL,
        bound_identity_hash CHAR(64) NULL,
        bound_computer_id INT NULL,
        CONSTRAINT PK_agent_enrollment_codes PRIMARY KEY CLUSTERED (code_hash),
        CONSTRAINT FK_agent_enrollment_codes_user FOREIGN KEY (created_by)
            REFERENCES dbo.users(id),
        CONSTRAINT FK_agent_enrollment_codes_computer FOREIGN KEY (bound_computer_id)
            REFERENCES dbo.computers(id),
        CONSTRAINT CK_agent_enrollment_codes_binding CHECK (
            (consumed_at IS NULL AND bound_identity_hash IS NULL AND bound_computer_id IS NULL)
            OR (consumed_at IS NOT NULL AND bound_identity_hash IS NOT NULL AND bound_computer_id IS NOT NULL)
        )
    );
    CREATE INDEX IX_agent_enrollment_codes_expiry
        ON dbo.agent_enrollment_codes (expires_at);
END;
GO

-- machine_uuid is optional. SQL Server UNIQUE constraints allow only one NULL,
-- so retain uniqueness for real UUIDs with a filtered unique index instead.
DECLARE @machine_uuid_constraint sysname;
SELECT TOP (1) @machine_uuid_constraint = kc.name
FROM sys.key_constraints AS kc
JOIN sys.index_columns AS ic
  ON ic.object_id = kc.parent_object_id
 AND ic.index_id = kc.unique_index_id
JOIN sys.columns AS col
  ON col.object_id = ic.object_id
 AND col.column_id = ic.column_id
WHERE kc.parent_object_id = OBJECT_ID(N'dbo.computers')
  AND kc.type = 'UQ'
  AND col.name = N'machine_uuid'
  AND ic.key_ordinal = 1
  AND NOT EXISTS (
      SELECT 1
      FROM sys.index_columns AS extra_ic
      WHERE extra_ic.object_id = ic.object_id
        AND extra_ic.index_id = ic.index_id
        AND extra_ic.key_ordinal > 1
  );
IF @machine_uuid_constraint IS NOT NULL
BEGIN
    DECLARE @drop_machine_uuid_constraint nvarchar(512);
    SET @drop_machine_uuid_constraint =
        N'ALTER TABLE dbo.computers DROP CONSTRAINT '
        + QUOTENAME(@machine_uuid_constraint);
    EXEC(@drop_machine_uuid_constraint);
END;
GO
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.computers')
      AND name = N'UX_computers_machine_uuid_not_null'
)
BEGIN
    CREATE UNIQUE NONCLUSTERED INDEX UX_computers_machine_uuid_not_null
        ON dbo.computers (machine_uuid)
        WHERE machine_uuid IS NOT NULL;
END;
GO
