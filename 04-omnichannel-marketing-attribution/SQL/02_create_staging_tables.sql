/*=============================================================================
  02_create_staging_tables.sql

  One landing table per source file, columns in exactly the file's order.
  BULK INSERT maps by position, so a staging table must carry NO extra columns:
  an IDENTITY or DEFAULT column here raises Msg 7301 (lesson from project 1).
  Load lineage therefore lives in stg.LoadLog, not on every row.
=============================================================================*/
USE MarketingAttributionBI;
GO

CREATE TABLE stg.dim_channel (
    ChannelID NVARCHAR(50), ChannelName NVARCHAR(200), ChannelGroup NVARCHAR(200));

CREATE TABLE stg.dim_campaign (
    CampaignID NVARCHAR(50), CanonicalCampaignName NVARCHAR(200), ChannelID NVARCHAR(50),
    Region NVARCHAR(100), Objective NVARCHAR(100), StartDate NVARCHAR(50));

CREATE TABLE stg.campaign_name_mapping (
    RawCampaignKey NVARCHAR(100), RawCampaignName NVARCHAR(200), CampaignID NVARCHAR(50));

CREATE TABLE stg.dim_date (
    [Date] NVARCHAR(50), [Year] NVARCHAR(10), MonthNo NVARCHAR(10), MonthName NVARCHAR(20),
    [Quarter] NVARCHAR(10), ISOWeek NVARCHAR(10), DayName NVARCHAR(20),
    FinancialYearStart NVARCHAR(10), FinancialYear NVARCHAR(10));

CREATE TABLE stg.fact_ad_spend (
    AdRowID NVARCHAR(50), [Date] NVARCHAR(50), CampaignID NVARCHAR(50), ChannelID NVARCHAR(50),
    Impressions NVARCHAR(50), Clicks NVARCHAR(50), SpendLocal NVARCHAR(50), Currency NVARCHAR(10));

CREATE TABLE stg.fact_leads (
    LeadID NVARCHAR(50), CreatedDate NVARCHAR(50), CampaignID NVARCHAR(50), ChannelID NVARCHAR(50),
    Segment NVARCHAR(50), Country NVARCHAR(100), LatestStage NVARCHAR(50), EstimatedValue NVARCHAR(50));

CREATE TABLE stg.fact_touchpoints (
    TouchpointID NVARCHAR(50), LeadID NVARCHAR(50), TouchDate NVARCHAR(50), CampaignID NVARCHAR(50),
    ChannelID NVARCHAR(50), TouchSequence NVARCHAR(10), TouchType NVARCHAR(50));

CREATE TABLE stg.fact_opportunities (
    OpportunityID NVARCHAR(50), LeadID NVARCHAR(50), CreatedDate NVARCHAR(50),
    OpportunityValue NVARCHAR(50), [Status] NVARCHAR(50));

CREATE TABLE stg.fact_revenue (
    RevenueID NVARCHAR(50), OpportunityID NVARCHAR(50), LeadID NVARCHAR(50),
    RevenueDate NVARCHAR(50), RevenueAmount NVARCHAR(50));

CREATE TABLE stg.security_user_access (
    UserEmail NVARCHAR(200), [Role] NVARCHAR(100), Region NVARCHAR(100));

CREATE TABLE stg.LoadLog (
    LoadLogID     INT IDENTITY(1,1) PRIMARY KEY,
    SourceFile    NVARCHAR(200) NOT NULL,
    TargetTable   NVARCHAR(200) NOT NULL,
    RowsLoaded    INT           NOT NULL,
    ExpectedRows  INT           NOT NULL,
    LoadedAtUtc   DATETIME2(0)  NOT NULL DEFAULT SYSUTCDATETIME(),
    DurationMs    INT           NOT NULL);
GO
PRINT '10 staging tables + stg.LoadLog created.';
GO
