-- =============================================================================
-- ContentVersion Mapping (ContentVersion → mapping."contentVersion")
-- Enables read + write through Axway /update-content-version endpoint
-- =============================================================================
-- Axway write fields: title, pathOnClient, versionData, cPQ_File_Type__c
-- FirstPublishLocationId: links the file directly to a record (e.g. Lead)
-- cPQ_File_Type__c is MANDATORY per Axway spec (default: "Others")
-- The trigger captures both Id AND ContentDocumentId via RETURNING so that
-- callers can chain ContentDocumentId into ContentDocumentLink creation.
-- =============================================================================

BEGIN;

-- 1. Enable writes on the ContentVersion foreign table
DO $$ BEGIN
    ALTER FOREIGN TABLE starhub_itxp2dev."ContentVersion" OPTIONS (ADD allow_writes 'true');
EXCEPTION WHEN OTHERS THEN
    ALTER FOREIGN TABLE starhub_itxp2dev."ContentVersion" OPTIONS (SET allow_writes 'true');
END $$;

-- 2. Drop existing view + trigger
DROP VIEW IF EXISTS mapping."contentVersion" CASCADE;
DROP VIEW IF EXISTS tmf."contentVersion" CASCADE;

-- 3. Create ContentVersion view in mapping schema
CREATE VIEW mapping."contentVersion" AS
SELECT
    "Id"                       AS id,
    "Title"                    AS title,
    "Description"              AS description,
    "PathOnClient"             AS "pathOnClient",
    "VersionData"              AS "versionData",
    "FirstPublishLocationId"   AS "firstPublishLocationId",
    "ContentDocumentId"        AS "contentDocumentId",
    "ContentSize"              AS "contentSize",
    "FileType"                 AS "mimeType",
    "FileExtension"            AS "fileExtension",
    "VersionNumber"            AS "versionNumber",
    "PublishStatus"            AS "publishStatus",
    "ContentLocation"          AS "contentLocation",
    "CPQ_File_Type__c"         AS "fileType",
    "CPQ_Content_Number__c"    AS "contentNumber",
    "OwnerId"                  AS "ownerId",
    "CreatedDate"              AS "createdDate",
    "LastModifiedDate"         AS "lastModifiedDate"
FROM starhub_itxp2dev."ContentVersion";

-- 4. Create INSTEAD OF INSERT trigger function
CREATE OR REPLACE FUNCTION mapping.fn_insert_content_version()
RETURNS TRIGGER AS $$
DECLARE
    new_id text;
    new_doc_id text;
BEGIN
    INSERT INTO starhub_itxp2dev."ContentVersion" (
        "Title",
        "PathOnClient",
        "VersionData",
        "Description",
        "FirstPublishLocationId",
        "CPQ_File_Type__c"
    ) VALUES (
        NEW.title,
        NEW."pathOnClient",
        NEW."versionData",
        NEW.description,
        NEW."firstPublishLocationId",
        COALESCE(NEW."fileType", 'Others')
    ) RETURNING "Id", "ContentDocumentId" INTO new_id, new_doc_id;

    NEW.id = new_id;
    NEW."contentDocumentId" = new_doc_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 5. Attach trigger
DROP TRIGGER IF EXISTS trg_insert_content_version ON mapping."contentVersion";
CREATE TRIGGER trg_insert_content_version
    INSTEAD OF INSERT ON mapping."contentVersion"
    FOR EACH ROW
    EXECUTE FUNCTION mapping.fn_insert_content_version();

COMMIT;

-- 6. Verify
SELECT 'contentVersion view created' AS status,
       count(*) AS column_count
FROM information_schema.columns
WHERE table_schema = 'mapping' AND table_name = 'contentVersion';
