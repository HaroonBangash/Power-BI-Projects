/*=============================================================================
  07_indexes_and_constraints.sql
  -----------------------------------------------------------------------------
  Project : Enterprise Supply Chain Control Tower
  Phase   : 3 - SQL Data Platform
  Purpose : Declare foreign keys and supporting indexes, after the data is in.

  Why foreign keys are declared at all
  ------------------------------------
  This is a load-once analytical store, so referential integrity could in
  principle be left to trust. It is not, for two reasons.

  First, they are executable documentation: a reader can derive the star schema
  from the constraints alone, without reading the transformation script.

  Second - and this is the specific reason the DATE foreign keys exist - the
  supplied calendar ended at 2026-08-31 while fact dates reached 2026-10-07.
  That defect passed silently through a CSV import and would have surfaced only
  as mysterious blank rows in Power BI. FK_*_Date makes the same defect fail at
  load time with a named constraint, which is where it should fail.

  Every date column that can hold a fact date is constrained, not just the
  primary one, because the columns that actually overflowed were the delivery
  and receipt dates rather than the order dates. Constraining only OrderDate
  would guard the one column that never broke. NULLs are permitted by a foreign
  key, so the deliberately NULL actual/scheduled columns are unaffected.

  A note on the indexes
  ---------------------
  These do NOT speed up Power BI refresh. An Import-mode refresh scans each
  table once, and a scan cannot be improved by an index. They exist to serve
  foreign key validation, the Python forecasting extract, ad-hoc SQL analysis,
  and any future DirectQuery or composite evaluation. Claiming otherwise in the
  documentation would be false.

  Idempotent: existing objects are dropped before being recreated.
=============================================================================*/

USE SupplyChainBI;
GO
SET NOCOUNT ON;
GO

/*=============================================================================
  1. Drop existing foreign keys so the script can be re-run
=============================================================================*/
DECLARE @sql nvarchar(max) = N'';

SELECT @sql = @sql + N'ALTER TABLE ' + QUOTENAME(SCHEMA_NAME(t.schema_id))
            + N'.' + QUOTENAME(t.name)
            + N' DROP CONSTRAINT ' + QUOTENAME(fk.name) + N';' + CHAR(10)
FROM   sys.foreign_keys AS fk
JOIN   sys.tables       AS t ON t.object_id = fk.parent_object_id
WHERE  SCHEMA_NAME(t.schema_id) = 'dbo';

IF LEN(@sql) > 0 EXEC sys.sp_executesql @sql;
PRINT 'Existing foreign keys dropped.';
GO

/*=============================================================================
  2. Dimension-to-dimension foreign key
=============================================================================*/
ALTER TABLE dbo.DimProduct WITH CHECK
    ADD CONSTRAINT FK_DimProduct_Supplier
    FOREIGN KEY (PrimarySupplierID) REFERENCES dbo.DimSupplier (SupplierID);
GO

/*=============================================================================
  3. FactSalesOrders
=============================================================================*/
ALTER TABLE dbo.FactSalesOrders WITH CHECK
    ADD CONSTRAINT FK_FactSalesOrders_Product
    FOREIGN KEY (ProductID) REFERENCES dbo.DimProduct (ProductID);

ALTER TABLE dbo.FactSalesOrders WITH CHECK
    ADD CONSTRAINT FK_FactSalesOrders_Warehouse
    FOREIGN KEY (WarehouseID) REFERENCES dbo.DimWarehouse (WarehouseID);

ALTER TABLE dbo.FactSalesOrders WITH CHECK
    ADD CONSTRAINT FK_FactSalesOrders_OrderDate
    FOREIGN KEY (OrderDate) REFERENCES dbo.DimDate ([Date]);

ALTER TABLE dbo.FactSalesOrders WITH CHECK
    ADD CONSTRAINT FK_FactSalesOrders_PromisedDate
    FOREIGN KEY (PromisedDeliveryDate) REFERENCES dbo.DimDate ([Date]);

ALTER TABLE dbo.FactSalesOrders WITH CHECK
    ADD CONSTRAINT FK_FactSalesOrders_ActualDeliveryDate
    FOREIGN KEY (ActualDeliveryDate) REFERENCES dbo.DimDate ([Date]);

ALTER TABLE dbo.FactSalesOrders WITH CHECK
    ADD CONSTRAINT FK_FactSalesOrders_ScheduledDeliveryDate
    FOREIGN KEY (ScheduledDeliveryDate) REFERENCES dbo.DimDate ([Date]);
GO

/*=============================================================================
  4. FactPurchaseOrders
=============================================================================*/
ALTER TABLE dbo.FactPurchaseOrders WITH CHECK
    ADD CONSTRAINT FK_FactPurchaseOrders_Product
    FOREIGN KEY (ProductID) REFERENCES dbo.DimProduct (ProductID);

ALTER TABLE dbo.FactPurchaseOrders WITH CHECK
    ADD CONSTRAINT FK_FactPurchaseOrders_Supplier
    FOREIGN KEY (SupplierID) REFERENCES dbo.DimSupplier (SupplierID);

ALTER TABLE dbo.FactPurchaseOrders WITH CHECK
    ADD CONSTRAINT FK_FactPurchaseOrders_Warehouse
    FOREIGN KEY (WarehouseID) REFERENCES dbo.DimWarehouse (WarehouseID);

ALTER TABLE dbo.FactPurchaseOrders WITH CHECK
    ADD CONSTRAINT FK_FactPurchaseOrders_OrderDate
    FOREIGN KEY (OrderDate) REFERENCES dbo.DimDate ([Date]);

ALTER TABLE dbo.FactPurchaseOrders WITH CHECK
    ADD CONSTRAINT FK_FactPurchaseOrders_ExpectedReceiptDate
    FOREIGN KEY (ExpectedReceiptDate) REFERENCES dbo.DimDate ([Date]);

ALTER TABLE dbo.FactPurchaseOrders WITH CHECK
    ADD CONSTRAINT FK_FactPurchaseOrders_ActualReceiptDate
    FOREIGN KEY (ActualReceiptDate) REFERENCES dbo.DimDate ([Date]);

ALTER TABLE dbo.FactPurchaseOrders WITH CHECK
    ADD CONSTRAINT FK_FactPurchaseOrders_ScheduledReceiptDate
    FOREIGN KEY (ScheduledReceiptDate) REFERENCES dbo.DimDate ([Date]);
GO

/*=============================================================================
  5. FactShipments
  ---------------------------------------------------------------------------
  FK_FactShipments_SalesOrder is what makes the INNER JOIN in
  analytics.vw_Shipments provably safe: the engine will not permit a shipment
  without a parent order, so the join that resolves ProductID cannot lose rows.
=============================================================================*/
ALTER TABLE dbo.FactShipments WITH CHECK
    ADD CONSTRAINT FK_FactShipments_SalesOrder
    FOREIGN KEY (SalesOrderID) REFERENCES dbo.FactSalesOrders (SalesOrderID);

ALTER TABLE dbo.FactShipments WITH CHECK
    ADD CONSTRAINT FK_FactShipments_Warehouse
    FOREIGN KEY (WarehouseID) REFERENCES dbo.DimWarehouse (WarehouseID);

ALTER TABLE dbo.FactShipments WITH CHECK
    ADD CONSTRAINT FK_FactShipments_ShipDate
    FOREIGN KEY (ShipDate) REFERENCES dbo.DimDate ([Date]);

ALTER TABLE dbo.FactShipments WITH CHECK
    ADD CONSTRAINT FK_FactShipments_ActualDeliveryDate
    FOREIGN KEY (ActualDeliveryDate) REFERENCES dbo.DimDate ([Date]);

ALTER TABLE dbo.FactShipments WITH CHECK
    ADD CONSTRAINT FK_FactShipments_ScheduledDeliveryDate
    FOREIGN KEY (ScheduledDeliveryDate) REFERENCES dbo.DimDate ([Date]);
GO

/*=============================================================================
  6. FactWeeklyDemand and FactInventorySnapshot
=============================================================================*/
ALTER TABLE dbo.FactWeeklyDemand WITH CHECK
    ADD CONSTRAINT FK_FactWeeklyDemand_Product
    FOREIGN KEY (ProductID) REFERENCES dbo.DimProduct (ProductID);

ALTER TABLE dbo.FactWeeklyDemand WITH CHECK
    ADD CONSTRAINT FK_FactWeeklyDemand_Warehouse
    FOREIGN KEY (WarehouseID) REFERENCES dbo.DimWarehouse (WarehouseID);

ALTER TABLE dbo.FactWeeklyDemand WITH CHECK
    ADD CONSTRAINT FK_FactWeeklyDemand_WeekStart
    FOREIGN KEY (WeekStart) REFERENCES dbo.DimDate ([Date]);

ALTER TABLE dbo.FactInventorySnapshot WITH CHECK
    ADD CONSTRAINT FK_FactInventorySnapshot_Product
    FOREIGN KEY (ProductID) REFERENCES dbo.DimProduct (ProductID);

ALTER TABLE dbo.FactInventorySnapshot WITH CHECK
    ADD CONSTRAINT FK_FactInventorySnapshot_Warehouse
    FOREIGN KEY (WarehouseID) REFERENCES dbo.DimWarehouse (WarehouseID);

ALTER TABLE dbo.FactInventorySnapshot WITH CHECK
    ADD CONSTRAINT FK_FactInventorySnapshot_SnapshotDate
    FOREIGN KEY (SnapshotDate) REFERENCES dbo.DimDate ([Date]);
GO

/*=============================================================================
  7. Check constraints
  ---------------------------------------------------------------------------
  Narrow and defensible. Each encodes a rule that is physically impossible to
  violate in a real supply chain, so a breach means the data is wrong.

  The actual/scheduled pair is constrained to be mutually exclusive. That is
  the invariant the whole date-splitting exercise exists to create, so it is
  worth having the database enforce it rather than trusting script 05.
=============================================================================*/
ALTER TABLE dbo.DimProduct WITH CHECK
    ADD CONSTRAINT CK_DimProduct_Costs
    CHECK (UnitCost >= 0 AND UnitPrice >= 0 AND LeadTimeDays > 0 AND SafetyStockUnits >= 0);

ALTER TABLE dbo.FactSalesOrders WITH CHECK
    ADD CONSTRAINT CK_FactSalesOrders_Quantity CHECK (Quantity > 0);

ALTER TABLE dbo.FactSalesOrders WITH CHECK
    ADD CONSTRAINT CK_FactSalesOrders_DateExclusivity
    CHECK (ActualDeliveryDate IS NULL OR ScheduledDeliveryDate IS NULL);

ALTER TABLE dbo.FactSalesOrders WITH CHECK
    ADD CONSTRAINT CK_FactSalesOrders_DeliveryAfterOrder
    CHECK (ActualDeliveryDate IS NULL OR ActualDeliveryDate >= OrderDate);

ALTER TABLE dbo.FactPurchaseOrders WITH CHECK
    ADD CONSTRAINT CK_FactPurchaseOrders_Quantity CHECK (QuantityOrdered > 0);

ALTER TABLE dbo.FactPurchaseOrders WITH CHECK
    ADD CONSTRAINT CK_FactPurchaseOrders_DefectRate
    CHECK (DefectRate >= 0 AND DefectRate <= 1);

ALTER TABLE dbo.FactPurchaseOrders WITH CHECK
    ADD CONSTRAINT CK_FactPurchaseOrders_DateExclusivity
    CHECK (ActualReceiptDate IS NULL OR ScheduledReceiptDate IS NULL);

ALTER TABLE dbo.FactPurchaseOrders WITH CHECK
    ADD CONSTRAINT CK_FactPurchaseOrders_ReceiptAfterOrder
    CHECK (ActualReceiptDate IS NULL OR ActualReceiptDate >= OrderDate);

ALTER TABLE dbo.FactShipments WITH CHECK
    ADD CONSTRAINT CK_FactShipments_DateExclusivity
    CHECK (ActualDeliveryDate IS NULL OR ScheduledDeliveryDate IS NULL);

ALTER TABLE dbo.FactShipments WITH CHECK
    ADD CONSTRAINT CK_FactShipments_DeliveryAfterShip
    CHECK (ActualDeliveryDate IS NULL OR ActualDeliveryDate >= ShipDate);

ALTER TABLE dbo.FactWeeklyDemand WITH CHECK
    ADD CONSTRAINT CK_FactWeeklyDemand_NonNegative
    CHECK (ActualDemandUnits >= 0 AND BaselineForecastUnits >= 0);

ALTER TABLE dbo.FactInventorySnapshot WITH CHECK
    ADD CONSTRAINT CK_FactInventorySnapshot_NonNegative
    CHECK (OnHandUnits >= 0 AND InboundUnits >= 0);
GO

/*=============================================================================
  8. Indexes
=============================================================================*/

-- DimProduct: supports the supplier drill and the FK above.
DROP INDEX IF EXISTS IX_DimProduct_Supplier ON dbo.DimProduct;
CREATE NONCLUSTERED INDEX IX_DimProduct_Supplier
    ON dbo.DimProduct (PrimarySupplierID);

/*  FactSalesOrders
    OrderDate leads its own index because it is the intended incremental
    refresh partition column: a RangeStart/RangeEnd predicate becomes a
    seekable range rather than a scan.                                       */
DROP INDEX IF EXISTS IX_FactSalesOrders_OrderDate ON dbo.FactSalesOrders;
CREATE NONCLUSTERED INDEX IX_FactSalesOrders_OrderDate
    ON dbo.FactSalesOrders (OrderDate)
    INCLUDE (ProductID, WarehouseID, Quantity, Revenue);

DROP INDEX IF EXISTS IX_FactSalesOrders_Product ON dbo.FactSalesOrders;
CREATE NONCLUSTERED INDEX IX_FactSalesOrders_Product
    ON dbo.FactSalesOrders (ProductID);

DROP INDEX IF EXISTS IX_FactSalesOrders_Warehouse ON dbo.FactSalesOrders;
CREATE NONCLUSTERED INDEX IX_FactSalesOrders_Warehouse
    ON dbo.FactSalesOrders (WarehouseID);

/*  FactPurchaseOrders
    Supplier leads because every procurement and scorecard query aggregates
    by supplier first.                                                       */
DROP INDEX IF EXISTS IX_FactPurchaseOrders_Supplier ON dbo.FactPurchaseOrders;
CREATE NONCLUSTERED INDEX IX_FactPurchaseOrders_Supplier
    ON dbo.FactPurchaseOrders (SupplierID)
    INCLUDE (OrderDate, POValue, ActualLeadTimeDays, ReceiptDelayDays, DefectRate);

DROP INDEX IF EXISTS IX_FactPurchaseOrders_OrderDate ON dbo.FactPurchaseOrders;
CREATE NONCLUSTERED INDEX IX_FactPurchaseOrders_OrderDate
    ON dbo.FactPurchaseOrders (OrderDate);

DROP INDEX IF EXISTS IX_FactPurchaseOrders_Product ON dbo.FactPurchaseOrders;
CREATE NONCLUSTERED INDEX IX_FactPurchaseOrders_Product
    ON dbo.FactPurchaseOrders (ProductID);

/*  FactShipments
    SalesOrderID supports the join in analytics.vw_Shipments and the FK.      */
DROP INDEX IF EXISTS IX_FactShipments_SalesOrder ON dbo.FactShipments;
CREATE NONCLUSTERED INDEX IX_FactShipments_SalesOrder
    ON dbo.FactShipments (SalesOrderID)
    INCLUDE (Carrier, FreightCost, ShipDate, ActualDeliveryDate);

DROP INDEX IF EXISTS IX_FactShipments_Carrier ON dbo.FactShipments;
CREATE NONCLUSTERED INDEX IX_FactShipments_Carrier
    ON dbo.FactShipments (Carrier, WarehouseID);

/*  Weekly facts
    The clustered PKs lead on date, which serves date-range scans. These
    indexes invert the order to serve the per-series reads the Python
    forecasting extract performs: all weeks for one product-warehouse.        */
DROP INDEX IF EXISTS IX_FactWeeklyDemand_Series ON dbo.FactWeeklyDemand;
CREATE NONCLUSTERED INDEX IX_FactWeeklyDemand_Series
    ON dbo.FactWeeklyDemand (ProductID, WarehouseID, WeekStart)
    INCLUDE (ActualDemandUnits, BaselineForecastUnits);

DROP INDEX IF EXISTS IX_FactInventorySnapshot_Series ON dbo.FactInventorySnapshot;
CREATE NONCLUSTERED INDEX IX_FactInventorySnapshot_Series
    ON dbo.FactInventorySnapshot (ProductID, WarehouseID, SnapshotDate)
    INCLUDE (OnHandUnits, InboundUnits);
GO

/*----------------------------------------------------------- confirmation --*/
SELECT
    ConstraintType = 'FOREIGN KEY',
    TableName      = OBJECT_NAME(fk.parent_object_id),
    ConstraintName = fk.name,
    IsTrusted      = CASE WHEN fk.is_not_trusted = 0 THEN 'YES' ELSE 'NO' END
FROM   sys.foreign_keys AS fk
WHERE  SCHEMA_NAME(fk.schema_id) = 'dbo'
UNION ALL
SELECT
    'CHECK',
    OBJECT_NAME(cc.parent_object_id),
    cc.name,
    CASE WHEN cc.is_not_trusted = 0 THEN 'YES' ELSE 'NO' END
FROM   sys.check_constraints AS cc
WHERE  SCHEMA_NAME(cc.schema_id) = 'dbo'
ORDER BY ConstraintType, TableName, ConstraintName;

SELECT
    UntrustedConstraints =
        (SELECT COUNT(*) FROM sys.foreign_keys WHERE is_not_trusted = 1)
      + (SELECT COUNT(*) FROM sys.check_constraints WHERE is_not_trusted = 1);
GO
