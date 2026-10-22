IF EXISTS (
    SELECT 1
    FROM sys.check_constraints
    WHERE name = N'CK_hardware_components_type'
      AND parent_object_id = OBJECT_ID(N'dbo.hardware_components')
)
BEGIN
    ALTER TABLE dbo.hardware_components
    DROP CONSTRAINT CK_hardware_components_type;
END;
GO

ALTER TABLE dbo.hardware_components
WITH CHECK ADD CONSTRAINT CK_hardware_components_type
CHECK (
    component_type IN (
        N'cpu',
        N'motherboard',
        N'gpu',
        N'ram',
        N'storage',
        N'network',
        N'keyboard',
        N'mouse'
    )
);
GO

ALTER TABLE dbo.hardware_components
CHECK CONSTRAINT CK_hardware_components_type;
GO
