-- =============================================================================
-- TMF620 ProductOffering Mapping (cspmb__Price_Item__c → mapping."productOffering")
-- READ ONLY — served by product TMF Server on port 8000 via TMF620 spec
-- =============================================================================
-- Maps CloudSense Price Item foreign table to TMF620 ProductOffering.
-- If a mapping.ProductOffering TABLE already exists (from BSS Magic setup),
-- we rename it to avoid conflict, then create the view.
-- =============================================================================

BEGIN;

-- 1. Backup existing table if it exists (rename, don't drop)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_tables
        WHERE schemaname = 'mapping' AND tablename = 'productOffering'
    ) THEN
        ALTER TABLE mapping."productOffering" RENAME TO "_orig_productOffering";
        RAISE NOTICE 'Renamed existing mapping.ProductOffering table to _orig_productOffering';
    END IF;
END $$;

-- 2. Drop existing views to allow column reorder
DROP VIEW IF EXISTS mapping."productOffering" CASCADE;
DROP VIEW IF EXISTS tmf."productOffering" CASCADE;

-- 3. Create ProductOffering view in mapping schema
-- Only TMF620-standard fields are included here. The TMF Server's JSONB parser
-- rejects columns that don't exist in the OpenAPI spec. Custom StarHub fields
-- (planType, bandwidth, etc.) are available through the /query endpoint instead.
CREATE VIEW mapping."productOffering" AS
SELECT
    "Id"                                 AS id,
    "Name"                               AS name,
    "cspmb__Price_Item_Description__c"   AS description,
    CASE
        WHEN "cspmb__Is_Active__c"::text = 'true' THEN 'active'
        ELSE 'retired'
    END                                  AS "lifecycleStatus",
    "cspmb__Version_Number__c"           AS version
FROM starhub_itxp2dev."cspmb__Price_Item__c";

COMMIT;

-- 4. Verify
SELECT 'productOffering view created' AS status,
       count(*) AS column_count
FROM information_schema.columns
WHERE table_schema = 'mapping' AND table_name = 'productOffering';
