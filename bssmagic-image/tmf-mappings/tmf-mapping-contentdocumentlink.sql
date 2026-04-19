-- =============================================================================
-- ContentDocumentLink Mapping (ContentDocumentLink → mapping."contentDocumentLink")
-- Enables read + write through Axway /content-document-link endpoint
-- =============================================================================
-- Axway write fields: contentDocumentId, linkedEntityId, shareType, visibility
-- =============================================================================

BEGIN;

-- 1. Enable writes on the ContentDocumentLink foreign table
DO $$ BEGIN
    ALTER FOREIGN TABLE starhub_itxp2dev."ContentDocumentLink" OPTIONS (ADD allow_writes 'true');
EXCEPTION WHEN OTHERS THEN
    ALTER FOREIGN TABLE starhub_itxp2dev."ContentDocumentLink" OPTIONS (SET allow_writes 'true');
END $$;

-- 2. Drop existing view + trigger
DROP VIEW IF EXISTS mapping."contentDocumentLink" CASCADE;
DROP VIEW IF EXISTS tmf."contentDocumentLink" CASCADE;

-- 3. Create ContentDocumentLink view in mapping schema
CREATE VIEW mapping."contentDocumentLink" AS
SELECT
    "Id"                  AS id,
    "ContentDocumentId"   AS "contentDocumentId",
    "LinkedEntityId"      AS "linkedEntityId",
    "ShareType"           AS "shareType",
    "Visibility"          AS visibility,
    "SystemModstamp"      AS "lastModifiedDate"
FROM starhub_itxp2dev."ContentDocumentLink";

-- 4. Create INSTEAD OF INSERT trigger function
CREATE OR REPLACE FUNCTION mapping.fn_insert_content_document_link()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO starhub_itxp2dev."ContentDocumentLink" (
        "ContentDocumentId",
        "LinkedEntityId",
        "ShareType",
        "Visibility"
    ) VALUES (
        NEW."contentDocumentId",
        NEW."linkedEntityId",
        NEW."shareType",
        NEW.visibility
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 5. Attach trigger
DROP TRIGGER IF EXISTS trg_insert_content_document_link ON mapping."contentDocumentLink";
CREATE TRIGGER trg_insert_content_document_link
    INSTEAD OF INSERT ON mapping."contentDocumentLink"
    FOR EACH ROW
    EXECUTE FUNCTION mapping.fn_insert_content_document_link();

COMMIT;

-- 6. Verify
SELECT 'contentDocumentLink view created' AS status,
       count(*) AS column_count
FROM information_schema.columns
WHERE table_schema = 'mapping' AND table_name = 'contentDocumentLink';
