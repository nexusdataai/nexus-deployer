-- =============================================================================
-- Attachment Mapping (Attachment → mapping."attachment")
-- Enables read + write through Axway /attachment endpoint
-- =============================================================================
-- Axway write fields: parentId, name, contentType, body
-- =============================================================================

BEGIN;

-- 1. Enable writes on the Attachment foreign table
DO $$ BEGIN
    ALTER FOREIGN TABLE starhub_itxp2dev."Attachment" OPTIONS (ADD allow_writes 'true');
EXCEPTION WHEN OTHERS THEN
    ALTER FOREIGN TABLE starhub_itxp2dev."Attachment" OPTIONS (SET allow_writes 'true');
END $$;

-- 2. Drop existing view + trigger
DROP VIEW IF EXISTS mapping."attachment" CASCADE;
DROP VIEW IF EXISTS tmf."attachment" CASCADE;

-- 3. Create Attachment view in mapping schema
CREATE VIEW mapping."attachment" AS
SELECT
    "Id"               AS id,
    "ParentId"         AS "parentId",
    "Name"             AS name,
    "ContentType"      AS "contentType",
    "Body"             AS body,
    "BodyLength"       AS "bodyLength",
    "Description"      AS description,
    "IsPrivate"        AS "isPrivate",
    "OwnerId"          AS "ownerId",
    "CreatedDate"      AS "createdDate",
    "LastModifiedDate" AS "lastModifiedDate"
FROM starhub_itxp2dev."Attachment";

-- 4. Create INSTEAD OF INSERT trigger function
CREATE OR REPLACE FUNCTION mapping.fn_insert_attachment()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO starhub_itxp2dev."Attachment" (
        "ParentId",
        "Name",
        "ContentType",
        "Body"
    ) VALUES (
        NEW."parentId",
        NEW.name,
        NEW."contentType",
        NEW.body
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 5. Attach trigger
DROP TRIGGER IF EXISTS trg_insert_attachment ON mapping."attachment";
CREATE TRIGGER trg_insert_attachment
    INSTEAD OF INSERT ON mapping."attachment"
    FOR EACH ROW
    EXECUTE FUNCTION mapping.fn_insert_attachment();

COMMIT;

-- 6. Verify
SELECT 'attachment view created' AS status,
       count(*) AS column_count
FROM information_schema.columns
WHERE table_schema = 'mapping' AND table_name = 'attachment';
