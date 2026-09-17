# Omnichannel Marketing Attribution Dataset

Built for multi-touch attribution, funnel analysis, campaign data cleaning and revenue attribution.

## Purpose
This dataset is **synthetic and portfolio-safe**. It is designed for an advanced Power BI project rather than a beginner dashboard.

## Suggested Architecture
Raw CSVs → SQL database / Fabric Lakehouse → Power Query / Dataflow → Semantic Model → Power BI Service

## Tables
- **fact_ad_spend.csv** — 80k paid-media performance rows
- **fact_touchpoints.csv** — Multi-touch customer journey events
- **fact_leads.csv** — CRM leads and funnel stage
- **fact_opportunities.csv** — Sales opportunities
- **fact_revenue.csv** — Closed-won revenue
- **campaign_name_mapping.csv** — Messy-name mapping table for Power Query
- **dim_campaign.csv** — Canonical campaign dimension
- **dim_channel.csv** — Marketing channel dimension
- **security_user_access.csv** — Regional RLS

## Suggested Relationships
- dim_campaign[CampaignID] 1:* ad spend / touchpoints / leads
- dim_channel[ChannelID] 1:* ad spend / touchpoints / leads
- fact_leads[LeadID] 1:* touchpoints / opportunities
- fact_opportunities[OpportunityID] 1:* revenue

## Advanced Tasks to Implement
1. Implement First Touch, Last Touch, Linear, Position-Based and Time-Decay attribution.
2. Create a disconnected attribution-model selector and recalculate attributed revenue/ROAS dynamically.
3. Resolve campaign aliases with Power Query/M and document data-quality rules.
4. Build Lead → MQL → SQL → Opportunity → Customer funnel conversion.
5. Calculate CAC, CPL, CPA, ROAS and revenue by channel/campaign.
6. Add currency conversion and regional dynamic RLS.

## Scaling Notes
Scale fact_touchpoints into the millions for DirectQuery/composite-model experiments. The starter data retains realistic multi-touch structure.
