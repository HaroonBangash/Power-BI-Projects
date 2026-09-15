SET NOCOUNT ON;
WITH s AS (
    SELECT SupplierID,
           CAST(SUM(CASE WHEN IsReceived=1 AND ReceiptDelayDays<=0 THEN 1.0 ELSE 0 END) AS float)
             / NULLIF(SUM(CASE WHEN IsReceived=1 THEN 1.0 ELSE 0 END),0)          AS OnTimePct,
           STDEV(CASE WHEN IsReceived=1 THEN CAST(ActualLeadTimeDays AS float) END) AS LeadSd,
           AVG(CAST(DefectRate AS float))                                          AS DefectRate,
           SUM(POValue)                                                            AS POValue
    FROM analytics.vw_PurchaseOrders GROUP BY SupplierID
),
b AS (SELECT MIN(OnTimePct) otLo, MAX(OnTimePct) otHi,
             MIN(LeadSd) lsLo, MAX(LeadSd) lsHi,
             MIN(DefectRate) dfLo, MAX(DefectRate) dfHi FROM s),
n AS (
    SELECT s.SupplierID, s.POValue, s.OnTimePct, s.LeadSd, s.DefectRate,
           (s.OnTimePct-b.otLo)/NULLIF(b.otHi-b.otLo,0)        AS OnTimeScore,
           1-(s.LeadSd -b.lsLo)/NULLIF(b.lsHi-b.lsLo,0)        AS RelScore,
           1-(s.DefectRate-b.dfLo)/NULLIF(b.dfHi-b.dfLo,0)     AS QualScore
    FROM s CROSS JOIN b
),
sc AS (
    SELECT *, 100*(0.45*OnTimeScore + 0.35*RelScore + 0.20*QualScore) AS Score FROM n
),
cl AS (
    SELECT *, CASE WHEN Score>=70 THEN 'Excellent' WHEN Score>=55 THEN 'Good'
                   WHEN Score>=40 THEN 'Needs Improvement' ELSE 'High Risk' END AS Cls
    FROM sc
)
SELECT Cls AS PerformanceClass, COUNT(*) AS Suppliers,
       CAST(100.0*SUM(POValue)/SUM(SUM(POValue)) OVER () AS decimal(6,2)) AS SpendPct,
       CAST(MIN(Score) AS decimal(6,2)) AS MinScore, CAST(MAX(Score) AS decimal(6,2)) AS MaxScore
FROM cl GROUP BY Cls
ORDER BY MinScore DESC;

SELECT 'RAW SPREAD' AS X,
       CAST(MIN(OnTimePct) AS decimal(8,4)) OnTimeLo, CAST(MAX(OnTimePct) AS decimal(8,4)) OnTimeHi,
       CAST(MIN(LeadSd) AS decimal(8,4)) LeadSdLo,   CAST(MAX(LeadSd) AS decimal(8,4)) LeadSdHi,
       CAST(MIN(DefectRate) AS decimal(8,5)) DefLo,  CAST(MAX(DefectRate) AS decimal(8,5)) DefHi,
       COUNT(*) AS Suppliers
FROM (SELECT SupplierID,
           CAST(SUM(CASE WHEN IsReceived=1 AND ReceiptDelayDays<=0 THEN 1.0 ELSE 0 END) AS float)
             / NULLIF(SUM(CASE WHEN IsReceived=1 THEN 1.0 ELSE 0 END),0) AS OnTimePct,
           STDEV(CASE WHEN IsReceived=1 THEN CAST(ActualLeadTimeDays AS float) END) AS LeadSd,
           AVG(CAST(DefectRate AS float)) AS DefectRate
      FROM analytics.vw_PurchaseOrders GROUP BY SupplierID) q;
