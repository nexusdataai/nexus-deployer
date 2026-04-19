-- =============================================================================
-- TMF699 SalesLead Mapping (Lead → mapping."salesLead")
-- Phase 2: Axway proxy mode
-- =============================================================================
-- Maps Salesforce Lead fields to TMF699-friendly names in the mapping schema.
-- INSTEAD OF INSERT trigger routes Lead creation through FDW -> Axway.
-- The trigger captures the Salesforce-generated Id via RETURNING so that
-- callers can chain it into ContentVersion.firstPublishLocationId.
-- =============================================================================

BEGIN;

-- 1. Enable writes on the Lead foreign table
DO $$ BEGIN
    ALTER FOREIGN TABLE starhub_itxp2dev."Lead" OPTIONS (ADD allow_writes 'true');
EXCEPTION WHEN OTHERS THEN
    ALTER FOREIGN TABLE starhub_itxp2dev."Lead" OPTIONS (SET allow_writes 'true');
END $$;

-- 2. Drop existing view + trigger so we can recreate with updated columns.
DROP VIEW IF EXISTS mapping."salesLead" CASCADE;
-- Clean up legacy tmf-schema view if it exists
DROP VIEW IF EXISTS tmf."salesLead" CASCADE;

-- 3. Create SalesLead view in the mapping schema
CREATE VIEW mapping."salesLead" AS
SELECT
    "Id"                                       AS id,
    "Company"                                  AS name,
    "Lead_Remarks__c"                          AS description,
    "Lead_Remarks__c"                          AS "leadRemarks",
    "Status"                                   AS status,
    "LeadSource"                               AS source,
    "FirstName"                                AS "givenName",
    "LastName"                                 AS "familyName",
    "Company"                                  AS "companyName",
    "Email"                                    AS email,
    "Phone"                                    AS phone,
    "MobilePhone"                              AS "mobilePhone",
    "CPQ_Mobile_Number_Type__c"                AS "mobileType",
    "Salutation"                               AS salutation,
    "RecordTypeId"                             AS "recordTypeId",
    "Customer_Type__c"                         AS "customerType",
    "Type_of_Services_Enquired__c"             AS "serviceTypeEnquired",
    "Products_Enquired__c"                     AS "productEnquired",
    "Business_Registration_Number_BRN__c"      AS brn,
    "OwnerId"                                  AS "ownerId",
    "Double_Bubble__c"                         AS "doubleBubble",
    "Referrer_Mobile__c"                       AS "referrerMobile",
    "Web_To_Lead_Owner_Dept__c"                AS "webToLeadOwnerDept",
    "How_did_you_know_about_this_promotion__c" AS "howDidYouKnowAboutThisPromotion",
    "Activity_Name__c"                         AS "activityName",
    "CurrencyIsoCode"                          AS "leadCurrency",
    "CreatedDate"                              AS "createdDate",
    "LastModifiedDate"                         AS "lastModifiedDate"
FROM starhub_itxp2dev."Lead";

-- 4. Create the insert trigger function
CREATE OR REPLACE FUNCTION mapping.fn_insert_sales_lead()
RETURNS TRIGGER AS $$
DECLARE
    new_id text;
BEGIN
    INSERT INTO starhub_itxp2dev."Lead" (
        "LastName",
        "FirstName",
        "Company",
        "Email",
        "Phone",
        "MobilePhone",
        "CPQ_Mobile_Number_Type__c",
        "Status",
        "LeadSource",
        "Salutation",
        "RecordTypeId",
        "Customer_Type__c",
        "Type_of_Services_Enquired__c",
        "Products_Enquired__c",
        "Business_Registration_Number_BRN__c",
        "Lead_Remarks__c",
        "OwnerId",
        "Double_Bubble__c",
        "Referrer_Mobile__c",
        "Web_To_Lead_Owner_Dept__c",
        "How_did_you_know_about_this_promotion__c",
        "Activity_Name__c",
        "CurrencyIsoCode"
    ) VALUES (
        NEW."familyName",
        NEW."givenName",
        NEW.name,
        NEW.email,
        NEW.phone,
        NEW."mobilePhone",
        NEW."mobileType",
        COALESCE(NEW.status, 'Open Lead'),
        NEW.source,
        NEW.salutation,
        NEW."recordTypeId",
        NEW."customerType",
        NEW."serviceTypeEnquired",
        NEW."productEnquired",
        NEW.brn,
        COALESCE(NEW."leadRemarks", NEW.description),
        NEW."ownerId",
        NEW."doubleBubble",
        NEW."referrerMobile",
        NEW."webToLeadOwnerDept",
        NEW."howDidYouKnowAboutThisPromotion",
        NEW."activityName",
        COALESCE(NEW."leadCurrency", 'SGD')
    ) RETURNING "Id" INTO new_id;

    -- Pass the Salesforce-generated Id back through RETURN NEW
    -- so that INSERT ... RETURNING id on the view captures it.
    NEW.id = new_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 5. Attach the trigger to the view
DROP TRIGGER IF EXISTS trg_insert_sales_lead ON mapping."salesLead";
CREATE TRIGGER trg_insert_sales_lead
    INSTEAD OF INSERT ON mapping."salesLead"
    FOR EACH ROW
    EXECUTE FUNCTION mapping.fn_insert_sales_lead();

COMMIT;

-- 6. Verify
SELECT 'salesLead view created' AS status,
       count(*) AS column_count
FROM information_schema.columns
WHERE table_schema = 'mapping' AND table_name = 'salesLead';
