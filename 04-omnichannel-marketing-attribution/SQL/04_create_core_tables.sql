/*=============================================================================
  04_create_core_tables.sql

  Typed, constrained star schema. Every foreign key is declared here and loaded
  WITH CHECK, so the engine trusts it (is_not_trusted = 0) - verified in 09.

  Grain of every fact:
    FactAdSpend            one billing line (AdRowID). Several lines can share
                           Date x Campaign x Channel; they differ in metrics and
                           usually in currency, so they are separate line items,
                           not duplicates.
    FactLead               one CRM lead
    FactTouchpoint         one marketing touch on a lead's journey
    FactOpportunity        one opportunity (exactly one per lead that has one)
    FactRevenue            one closed-won revenue booking (one per won opportunity)
    FactAttributionCredit  one touchpoint x one attribution model
=============================================================================*/
USE MarketingAttributionBI;
GO

-------------------------------------------------------------------- config ---
CREATE TABLE dbo.ModelConfig (
    ConfigKey    NVARCHAR(60)  NOT NULL CONSTRAINT PK_ModelConfig PRIMARY KEY,
    ConfigValue  NVARCHAR(100) NOT NULL,
    Description  NVARCHAR(600) NOT NULL);

---------------------------------------------------------------- dimensions ---
CREATE TABLE dbo.DimDate (
    [Date]              DATE         NOT NULL CONSTRAINT PK_DimDate PRIMARY KEY,
    [Year]              SMALLINT     NOT NULL,
    MonthNo             TINYINT      NOT NULL,
    MonthName           NVARCHAR(10) NOT NULL,
    MonthShort          NCHAR(3)     NOT NULL,
    [Quarter]           TINYINT      NOT NULL,
    QuarterLabel        NCHAR(7)     NOT NULL,   -- 2025 Q3
    YearMonth           INT          NOT NULL,   -- 202507, sort key
    YearMonthLabel      NCHAR(8)     NOT NULL,   -- Jul 2025
    MonthStart          DATE         NOT NULL,
    ISOWeek             TINYINT      NOT NULL,
    WeekStart           DATE         NOT NULL,   -- Monday
    DayName             NVARCHAR(10) NOT NULL,
    DayOfWeekNo         TINYINT      NOT NULL,   -- 1 = Monday
    FinancialYearStart  SMALLINT     NOT NULL,
    FinancialYear       NCHAR(4)     NOT NULL,   -- FY26 = Jul 2025 - Jun 2026
    FinancialMonthNo    TINYINT      NOT NULL,   -- 1 = July
    IsSourceCalendar    BIT          NOT NULL,   -- 1 where the supplied dim_date covers the day
    IsAfterAsOf         BIT          NOT NULL,   -- 1 for days after the as-of date: no actuals exist yet
    IsQuarterComplete   BIT          NOT NULL);  -- 1 when the whole quarter lies on or before the as-of date

CREATE TABLE dbo.DimRegion (
    Region  NVARCHAR(40) NOT NULL CONSTRAINT PK_DimRegion PRIMARY KEY);

CREATE TABLE dbo.DimChannel (
    ChannelID     NVARCHAR(10) NOT NULL CONSTRAINT PK_DimChannel PRIMARY KEY,
    ChannelName   NVARCHAR(60) NOT NULL CONSTRAINT UQ_DimChannel_Name UNIQUE,
    ChannelGroup  NVARCHAR(40) NOT NULL,
    IsPaidMedia   BIT          NOT NULL);

CREATE TABLE dbo.DimCampaign (
    CampaignID    NVARCHAR(10)  NOT NULL CONSTRAINT PK_DimCampaign PRIMARY KEY,
    CampaignName  NVARCHAR(120) NOT NULL CONSTRAINT UQ_DimCampaign_Name UNIQUE,
    ChannelID     NVARCHAR(10)  NOT NULL CONSTRAINT FK_DimCampaign_Channel REFERENCES dbo.DimChannel (ChannelID),
    Region        NVARCHAR(40)  NOT NULL CONSTRAINT FK_DimCampaign_Region REFERENCES dbo.DimRegion (Region),
    Objective     NVARCHAR(40)  NOT NULL,
    StartDate     DATE          NOT NULL);   -- recorded, but unreliable: see D-log

CREATE TABLE dbo.CampaignAlias (
    RawCampaignKey   NVARCHAR(20)  NOT NULL CONSTRAINT PK_CampaignAlias PRIMARY KEY,
    RawCampaignName  NVARCHAR(120) NOT NULL,
    CampaignID       NVARCHAR(10)  NOT NULL CONSTRAINT FK_CampaignAlias_Campaign REFERENCES dbo.DimCampaign (CampaignID));

CREATE TABLE dbo.FxRate (
    CurrencyCode   NCHAR(3)      NOT NULL,
    RateType       NVARCHAR(20)  NOT NULL,
    EffectiveFrom  DATE          NOT NULL,
    EffectiveTo    DATE          NOT NULL,
    RateToUSD      DECIMAL(18,6) NOT NULL CONSTRAINT CK_FxRate_Positive CHECK (RateToUSD > 0),
    Source         NVARCHAR(300) NOT NULL,
    CONSTRAINT PK_FxRate PRIMARY KEY (CurrencyCode, RateType, EffectiveFrom),
    CONSTRAINT CK_FxRate_Window CHECK (EffectiveTo >= EffectiveFrom));

CREATE TABLE dbo.DimAttributionModel (
    ModelKey     TINYINT       NOT NULL CONSTRAINT PK_DimAttributionModel PRIMARY KEY,
    ModelName    NVARCHAR(40)  NOT NULL CONSTRAINT UQ_DimAttributionModel_Name UNIQUE,
    SortOrder    TINYINT       NOT NULL,
    Description  NVARCHAR(400) NOT NULL,
    CampaignDispersionUSD DECIMAL(19,6) NULL);   -- set by 07: sum(v^2) / sum(v) of per-lead campaign credit, for the signal test

-- The funnel as an ordered axis. Disconnected in the model: the funnel visual
-- plots one bar per stage, each bar counting leads that reached AT LEAST that
-- stage, which no single fact column can express.
CREATE TABLE dbo.DimFunnelStage (
    StageRank   TINYINT       NOT NULL CONSTRAINT PK_DimFunnelStage PRIMARY KEY,
    StageName   NVARCHAR(20)  NOT NULL CONSTRAINT UQ_DimFunnelStage_Name UNIQUE,
    Definition  NVARCHAR(300) NOT NULL);

CREATE TABLE dbo.SecurityUserAccess (
    UserEmail  NVARCHAR(120) NOT NULL CONSTRAINT PK_SecurityUserAccess PRIMARY KEY,
    [Role]     NVARCHAR(60)  NOT NULL,
    Region     NVARCHAR(40)  NOT NULL);   -- a DimRegion value, or ALL

--------------------------------------------------------------------- facts ---
CREATE TABLE dbo.FactAdSpend (
    AdRowID               NVARCHAR(12)  NOT NULL CONSTRAINT PK_FactAdSpend PRIMARY KEY,
    [Date]                DATE          NOT NULL CONSTRAINT FK_FactAdSpend_Date REFERENCES dbo.DimDate ([Date]),
    CampaignID            NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactAdSpend_Campaign REFERENCES dbo.DimCampaign (CampaignID),
    ChannelID             NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactAdSpend_Channel REFERENCES dbo.DimChannel (ChannelID),
    Impressions           INT           NOT NULL CONSTRAINT CK_FactAdSpend_Impr CHECK (Impressions >= 0),
    Clicks                INT           NOT NULL,
    SpendLocal            DECIMAL(18,2) NOT NULL CONSTRAINT CK_FactAdSpend_Spend CHECK (SpendLocal > 0),
    CurrencyCode          NCHAR(3)      NOT NULL,
    FxRateToUSD           DECIMAL(18,6) NOT NULL,
    SpendUSD              DECIMAL(18,2) NOT NULL,
    IsBeforeCampaignStart BIT           NOT NULL,
    CONSTRAINT CK_FactAdSpend_Clicks CHECK (Clicks BETWEEN 0 AND Impressions));

CREATE TABLE dbo.FactLead (
    LeadID              NVARCHAR(10)  NOT NULL CONSTRAINT PK_FactLead PRIMARY KEY,
    CreatedDate         DATE          NOT NULL CONSTRAINT FK_FactLead_Date REFERENCES dbo.DimDate ([Date]),
    CampaignID          NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactLead_Campaign REFERENCES dbo.DimCampaign (CampaignID),
    ChannelID           NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactLead_Channel REFERENCES dbo.DimChannel (ChannelID),
    Segment             NVARCHAR(20)  NOT NULL,
    Country             NVARCHAR(40)  NOT NULL,
    EstimatedValue      DECIMAL(18,2) NOT NULL,
    LatestStageLabel    NVARCHAR(20)  NOT NULL,   -- as supplied by the CRM
    DerivedStage        NVARCHAR(20)  NOT NULL,   -- from evidence: see 06
    StageRank           TINYINT       NOT NULL,   -- 1 Lead .. 5 Customer
    ReachedMQL          BIT           NOT NULL,
    ReachedSQL          BIT           NOT NULL,
    HasOpportunity      BIT           NOT NULL,
    IsWon               BIT           NOT NULL,
    IsStageLabelStale   BIT           NOT NULL,
    TouchCount          TINYINT       NOT NULL,
    DistinctChannels    TINYINT       NOT NULL,
    SequenceContradictsDate BIT       NOT NULL,
    CONSTRAINT CK_FactLead_Stage CHECK (StageRank BETWEEN 1 AND 5));

CREATE TABLE dbo.FactTouchpoint (
    TouchpointID          NVARCHAR(12) NOT NULL CONSTRAINT PK_FactTouchpoint PRIMARY KEY,
    LeadID                NVARCHAR(10) NOT NULL CONSTRAINT FK_FactTouchpoint_Lead REFERENCES dbo.FactLead (LeadID),
    TouchDate             DATE         NOT NULL CONSTRAINT FK_FactTouchpoint_Date REFERENCES dbo.DimDate ([Date]),
    CampaignID            NVARCHAR(10) NOT NULL CONSTRAINT FK_FactTouchpoint_Campaign REFERENCES dbo.DimCampaign (CampaignID),
    ChannelID             NVARCHAR(10) NOT NULL CONSTRAINT FK_FactTouchpoint_Channel REFERENCES dbo.DimChannel (ChannelID),
    TouchType             NVARCHAR(20) NOT NULL,
    SourceTouchSequence   TINYINT      NOT NULL,   -- as supplied; contradicts the calendar for 71% of leads
    JourneyPosition       TINYINT      NOT NULL,   -- by TouchDate, tie-break SourceTouchSequence
    JourneyLength         TINYINT      NOT NULL,
    DaysBeforeLead        SMALLINT     NOT NULL,   -- lead CreatedDate minus TouchDate
    -- Where the touch sits in its journey. This is what separates the models:
    -- First Touch credits only 'First', Last Touch only 'Last'. Persisted, so
    -- the rule lives in one place and is indexed like any other column.
    PositionBand AS CAST(CASE WHEN JourneyLength = 1 THEN N'Only touch'
                              WHEN JourneyPosition = 1 THEN N'First'
                              WHEN JourneyPosition = JourneyLength THEN N'Last'
                              ELSE N'Middle' END AS NVARCHAR(10)) PERSISTED,
    PositionBandOrder AS CAST(CASE WHEN JourneyLength = 1 THEN 4
                                   WHEN JourneyPosition = 1 THEN 1
                                   WHEN JourneyPosition = JourneyLength THEN 3
                                   ELSE 2 END AS TINYINT) PERSISTED,
    CONSTRAINT UQ_FactTouchpoint_Position UNIQUE (LeadID, JourneyPosition),
    CONSTRAINT CK_FactTouchpoint_Days CHECK (DaysBeforeLead >= 0));

CREATE TABLE dbo.FactOpportunity (
    OpportunityID     NVARCHAR(10)  NOT NULL CONSTRAINT PK_FactOpportunity PRIMARY KEY,
    LeadID            NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactOpportunity_Lead REFERENCES dbo.FactLead (LeadID)
                                             CONSTRAINT UQ_FactOpportunity_Lead UNIQUE,
    CreatedDate       DATE          NOT NULL CONSTRAINT FK_FactOpportunity_Date REFERENCES dbo.DimDate ([Date]),
    OpportunityValue  DECIMAL(18,2) NOT NULL,
    [Status]          NVARCHAR(20)  NOT NULL CONSTRAINT CK_FactOpportunity_Status CHECK ([Status] IN (N'Open', N'Closed Won', N'Closed Lost')),
    IsAfterAsOf       BIT           NOT NULL);

CREATE TABLE dbo.FactRevenue (
    RevenueID      NVARCHAR(10)  NOT NULL CONSTRAINT PK_FactRevenue PRIMARY KEY,
    OpportunityID  NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactRevenue_Opportunity REFERENCES dbo.FactOpportunity (OpportunityID)
                                          CONSTRAINT UQ_FactRevenue_Opportunity UNIQUE,
    LeadID         NVARCHAR(10)  NOT NULL CONSTRAINT FK_FactRevenue_Lead REFERENCES dbo.FactLead (LeadID),
    RevenueDate    DATE          NOT NULL CONSTRAINT FK_FactRevenue_Date REFERENCES dbo.DimDate ([Date]),
    RevenueUSD     DECIMAL(18,2) NOT NULL CONSTRAINT CK_FactRevenue_Positive CHECK (RevenueUSD > 0),
    IsAfterAsOf    BIT           NOT NULL);

CREATE TABLE dbo.FactAttributionCredit (
    TouchpointID          NVARCHAR(12)  NOT NULL CONSTRAINT FK_Credit_Touchpoint REFERENCES dbo.FactTouchpoint (TouchpointID),
    ModelKey              TINYINT       NOT NULL CONSTRAINT FK_Credit_Model REFERENCES dbo.DimAttributionModel (ModelKey),
    LeadID                NVARCHAR(10)  NOT NULL CONSTRAINT FK_Credit_Lead REFERENCES dbo.FactLead (LeadID),
    CampaignID            NVARCHAR(10)  NOT NULL CONSTRAINT FK_Credit_Campaign REFERENCES dbo.DimCampaign (CampaignID),
    ChannelID             NVARCHAR(10)  NOT NULL CONSTRAINT FK_Credit_Channel REFERENCES dbo.DimChannel (ChannelID),
    TouchDate             DATE          NOT NULL CONSTRAINT FK_Credit_TouchDate REFERENCES dbo.DimDate ([Date]),
    RevenueDate           DATE          NULL     CONSTRAINT FK_Credit_RevenueDate REFERENCES dbo.DimDate ([Date]),
    CreditWeight          DECIMAL(19,15) NOT NULL CONSTRAINT CK_Credit_Weight CHECK (CreditWeight BETWEEN 0 AND 1),
    AttributedRevenueUSD  DECIMAL(19,6)  NOT NULL,
    IsRevenueAfterAsOf    BIT            NOT NULL,
    CONSTRAINT PK_FactAttributionCredit PRIMARY KEY (TouchpointID, ModelKey));
GO
PRINT 'Core tables created: 10 dimension/config tables, 6 fact tables.';
GO
