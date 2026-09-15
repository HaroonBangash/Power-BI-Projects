SET NOCOUNT ON;
WITH s AS (
    SELECT SupplierID,
           CAST(SUM(CASE WHEN IsReceived=1 AND ReceiptDelayDays<=0 THEN 1.0 ELSE 0 END) AS float)
             / NULLIF(SUM(CASE WHEN IsReceived=1 THEN 1.0 ELSE 0 END),0) AS OnTimePct,
           STDEV(CASE WHEN IsReceived=1 THEN CAST(ActualLeadTimeDays AS float) END) AS LeadSd,
           AVG(CAST(DefectRate AS float)) AS DefectRate,
           AVG(CASE WHEN IsReceived=1 THEN CAST(ActualLeadTimeDays AS float) END) AS AvgLead,
           SUM(POValue) AS POValue, COUNT(*) AS POs
    FROM analytics.vw_PurchaseOrders GROUP BY SupplierID),
b AS (SELECT MIN(OnTimePct) otLo,MAX(OnTimePct) otHi,MIN(LeadSd) lsLo,MAX(LeadSd) lsHi,
             MIN(DefectRate) dfLo,MAX(DefectRate) dfHi FROM s),
sc AS (SELECT s.*,
       (s.OnTimePct-b.otLo)/(b.otHi-b.otLo) OnTimeScore,
       1-(s.LeadSd-b.lsLo)/(b.lsHi-b.lsLo)  RelScore,
       1-(s.DefectRate-b.dfLo)/(b.dfHi-b.dfLo) QualScore
       FROM s CROSS JOIN b),
f AS (SELECT *, 100*(0.45*OnTimeScore+0.35*RelScore+0.20*QualScore) Score FROM sc),
g AS (SELECT *, CASE WHEN Score>=70 THEN 'Excellent' WHEN Score>=55 THEN 'Good'
                     WHEN Score>=40 THEN 'Needs Improvement' ELSE 'High Risk' END Cls,
             DENSE_RANK() OVER (ORDER BY Score DESC) Rnk FROM f)
SELECT Cls AS Class, g.SupplierID, d.SupplierName,
       CAST(OnTimePct*100 AS decimal(6,2)) AS [OnTime%],
       CAST(LeadSd AS decimal(6,2)) AS LeadSd,
       CAST(AvgLead AS decimal(6,2)) AS AvgLead,
       CAST(DefectRate*100 AS decimal(6,3)) AS [Defect%],
       CAST(OnTimeScore AS decimal(6,4)) AS OnTimeScore,
       CAST(RelScore AS decimal(6,4)) AS RelScore,
       CAST(QualScore AS decimal(6,4)) AS QualScore,
       CAST(Score AS decimal(6,2)) AS Score, Rnk AS Rank
FROM g JOIN analytics.vw_DimSupplier d ON d.SupplierID=g.SupplierID
WHERE g.SupplierID IN (
    SELECT TOP 1 SupplierID FROM g WHERE Cls='Excellent' ORDER BY Score DESC UNION ALL
    SELECT TOP 1 SupplierID FROM g WHERE Cls='Good' ORDER BY Score DESC UNION ALL
    SELECT TOP 1 SupplierID FROM g WHERE Cls='Needs Improvement' ORDER BY Score DESC UNION ALL
    SELECT TOP 1 SupplierID FROM g WHERE Cls='High Risk' ORDER BY Score ASC)
ORDER BY Score DESC;
