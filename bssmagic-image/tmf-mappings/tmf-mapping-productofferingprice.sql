-- =============================================================================
-- TMF620 ProductOfferingPrice Mapping
-- (cspmb__Pricing_Element__c → mapping."productOfferingPrice")
-- READ ONLY — served by product TMF Server on port 8000 via TMF620 spec
-- =============================================================================

BEGIN;

-- 1. Backup existing table if it exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_tables
        WHERE schemaname = 'mapping' AND tablename = 'productOfferingPrice'
    ) THEN
        ALTER TABLE mapping."productOfferingPrice" RENAME TO "_orig_productOfferingPrice";
        RAISE NOTICE 'Renamed existing mapping.ProductOfferingPrice table to _orig_productOfferingPrice';
    END IF;
END $$;

-- 2. Drop existing views
DROP VIEW IF EXISTS mapping."productOfferingPrice" CASCADE;
DROP VIEW IF EXISTS tmf."productOfferingPrice" CASCADE;

-- 3. Create ProductOfferingPrice view in mapping schema
CREATE VIEW mapping."productOfferingPrice" AS
SELECT
    "Id"                                AS id,
    "Name"                              AS name,
    "cspmb__description__c"             AS description,
    "cspmb__key__c"                     AS "priceKey",
    "cspmb__label__c"                   AS "displayLabel",
    "cspmb__commercial_product__c"      AS "productOfferingId",
    "cspmb__pricing_element_type__c"    AS "priceTypeRef",
    "cspmb__effective_start_date__c"    AS "validForStartDateTime",
    "cspmb__effective_end_date__c"      AS "validForEndDateTime",
    "cspmb__required__c"                AS "isRequired",
    "cspmb__user_selectable__c"         AS "isUserSelectable",
    "External_ID__c"                    AS "externalId",
    "CurrencyIsoCode"                   AS "currencyCode",
    "LastModifiedDate"                  AS "lastUpdate",
    "CreatedDate"                       AS "createdDate"
FROM starhub_itxp2dev."cspmb__Pricing_Element__c";

COMMIT;

-- 4. Verify
SELECT 'productOfferingPrice view created' AS status,
       count(*) AS column_count
FROM information_schema.columns
WHERE table_schema = 'mapping' AND table_name = 'productOfferingPrice';
