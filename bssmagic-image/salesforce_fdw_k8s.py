import json
import os
import requests
import uuid
import pprint
import urllib.error
import urllib.parse
import urllib.request
from queue import Queue
from threading import Thread
from datetime import datetime
from multicorn import ColumnDefinition, ForeignDataWrapper, TableDefinition
from multicorn.utils import DEBUG, ERROR, INFO, WARNING, log_to_postgres

from .salesforce_fdw_services import (
    CaseInsensitiveDict,
    _get_oauth_token,
    _get_sobject_describe,
    _get_sobjects,
    _map_sf_type_to_pg,
    parseToQueue,
    _get_sobject_record_counts,
)


# =========================================================================
# Axway Proxy Write Configuration
# =========================================================================
# Maps Salesforce object types to their Axway write endpoint and field name
# translation. Reads (SOQL) are already routed through Axway in execute().
# Only writes require per-object routing because Axway exposes dedicated
# REST endpoints for each writable object with custom field names.
#
# ALL URLs are read from environment variables so that switching between
# environments (SIT / UAT / PROD) only requires updating the Secrets
# Manager secret — no image rebuild needed. UAT values are hardcoded as
# defaults for backward compatibility.
#
# Environment variables (set via K8s from Secrets Manager):
#   AXWAY_TOKEN_URL            - OAuth token endpoint
#   AXWAY_QUERY_URL            - SOQL read/query endpoint
#   AXWAY_CLIENT_ID            - OAuth client ID
#   AXWAY_CLIENT_SECRET        - OAuth client secret
#   AXWAY_KEY_ID               - API key ID
#   AXWAY_PROVIDER_ORG         - Provider org code
#   AXWAY_LEAD_CREATE_URL      - Lead creation endpoint
#   AXWAY_CONTENT_VERSION_URL  - ContentVersion create/update endpoint
#   AXWAY_CONTENT_DOCUMENT_LINK_URL - ContentDocumentLink endpoint
#   AXWAY_ATTACHMENT_URL       - Attachment endpoint
# =========================================================================

AXWAY_WRITE_CONFIG = {
    'Lead': {
        'url': os.environ.get(
            'AXWAY_LEAD_CREATE_URL',
            'https://api-uat.starhub.com/product/stock-management/pp/v1/create-lead',
        ),
        'field_map': {
            'LastName': 'lastName',
            'FirstName': 'firstName',
            'Company': 'company',
            'Email': 'email',
            'MobilePhone': 'mobilePhone',
            'Status': 'leadStatus',
            'LeadSource': 'leadSource',
            'Salutation': 'salutation',
            'RecordTypeId': 'recordTypeId',
            'Customer_Type__c': 'customerType',
            'Type_of_Services_Enquired__c': 'serviceTypeEnquired',
            'Products_Enquired__c': 'productEnquired',
            'Business_Registration_Number_BRN__c': 'brn',
            'Lead_Remarks__c': 'leadRemarks',
            'OwnerId': 'ownerId',
            'Double_Bubble__c': 'doubleBubble',
            'Referrer_Mobile__c': 'referrerMobile',
            'Web_To_Lead_Owner_Dept__c': 'webToLeadOwnerDept',
            'How_did_you_know_about_this_promotion__c': 'howDidYouKnowAboutThisPromotion',
            'Activity_Name__c': 'activityName',
            'CurrencyIsoCode': 'leadCurrency',
        },
    },
    'ContentVersion': {
        'url': os.environ.get(
            'AXWAY_CONTENT_VERSION_URL',
            'https://api-uat.starhub.com/common/document-management/pp/v1/update-content-version',
        ),
        'field_map': {
            'Title': 'title',
            'PathOnClient': 'pathOnClient',
            'VersionData': 'versionData',
            'Description': 'description',
            'FirstPublishLocationId': 'firstPublishLocationId',
            'CPQ_File_Type__c': 'cPQ_File_Type__c',
        },
    },
    'ContentDocumentLink': {
        'url': os.environ.get(
            'AXWAY_CONTENT_DOCUMENT_LINK_URL',
            'https://api-uat.starhub.com/common/document-management/pp/v1/content-document-link',
        ),
        'field_map': {
            'ContentDocumentId': 'contentDocumentId',
            'LinkedEntityId': 'linkedEntityId',
            'ShareType': 'shareType',
            'Visibility': 'visibility',
        },
    },
    'Attachment': {
        'url': os.environ.get(
            'AXWAY_ATTACHMENT_URL',
            'https://api-uat.starhub.com/common/document-management/pp/v1/attachment',
        ),
        'field_map': {
            'ParentId': 'parentId',
            'Name': 'name',
            'ContentType': 'contentType',
            'Body': 'body',
        },
    },
}

# Reverse mappings (Axway field -> Salesforce field) built once at import time.
# Used to translate Axway API responses back to Salesforce column names.
AXWAY_REVERSE_FIELD_MAPS = {}
for _obj, _cfg in AXWAY_WRITE_CONFIG.items():
    _rev = {v: k for k, v in _cfg['field_map'].items()}
    # Axway may return 'id' as lowercase; map it to Salesforce's 'Id'
    _rev.setdefault('id', 'Id')
    AXWAY_REVERSE_FIELD_MAPS[_obj] = _rev


class SalesforceForeignDataWrapper(ForeignDataWrapper):
    _startup_cost = 200  # ~milliseconds per salesforce API call

    def __init__(self, options, columns):
        log_to_postgres(
            f"-> FDW __init__ called (columns={len(columns)})",
            DEBUG,
        )
        super(SalesforceForeignDataWrapper, self).__init__(options, columns)

        self.columns = columns
        self.column_map = CaseInsensitiveDict(dict([(x, x) for x in columns]))

        self.obj_type = options.get("obj_type", None)
        if self.obj_type is None:
            log_to_postgres(
                "Missing required 'obj_type' option for Salesforce foreign table. "
                "The 'obj_type' must specify the Salesforce object name (e.g., 'Account', 'Contact', 'Opportunity'). "
                "Set this option when creating the foreign table: "
                "CREATE FOREIGN TABLE my_table (...) SERVER my_server OPTIONS (obj_type 'Account');",
                ERROR,
            )

        self.allow_writes = options.get("allow_writes", "false").lower() == "true"

        # Collect authentication parameters and check for missing ones
        self.client_id = options.get("client_id", None)
        self.client_secret = options.get("client_secret", None)
        self.username = options.get("username", None)
        self.password = options.get("password", None)
        self.login_server = options.get("login_server", None)
        self.instance_url = options.get("instance_url", None)
        self.key_id = options.get("key_id", None)
        self.provider_org = options.get("provider_org", None)
        self.api_version = options.get("api_version", "v63.0")

        missing_auth_params = []
        if self.client_id is None:
            missing_auth_params.append("client_id")
        if self.client_secret is None:
            missing_auth_params.append("client_secret")
        if self.login_server is None:
            missing_auth_params.append("login_server")
        if self.instance_url is None:
            missing_auth_params.append("instance_url")
        if self.key_id is None:
            missing_auth_params.append("key_id")
        if self.provider_org is None:
            missing_auth_params.append("provider_org")
        if self.api_version is None:
            missing_auth_params.append("api_version")

        if missing_auth_params:
            missing_list = "', '".join(missing_auth_params)
            log_to_postgres(
                f"Missing required Salesforce authentication parameters: '{missing_list}'. "
                "All authentication credentials must be provided to connect to Salesforce. "
                "Configure your foreign server with these options: "
                "CREATE SERVER my_salesforce_server FOREIGN DATA WRAPPER salesforce_fdw "
                "OPTIONS (client_id 'your_client_id', client_secret 'your_client_secret', "
                "username 'your_username', password 'your_password_with_security_token', "
                "login_server 'your_login_server');",
                ERROR,
            )

        self.sortableFields = set()  
        self.nillableFields = set()
        self.updateableFields = set()
        self.createDefaultFields = set()
        self.createableFields = set()
        for column_name, column in self.columns.items():
            if column.options.get("sortable", "false").lower() == "true":
                self.sortableFields.add(column_name)
            if column.options.get("nillable", "true").lower() == "true":
                self.nillableFields.add(column_name)
            if column.options.get("updateable", "true").lower() == "true":
                self.updateableFields.add(column_name)
            if column.options.get("defaultedoncreate", "false").lower() == "true":
                self.createDefaultFields.add(column_name)
            if column.options.get("createable", "true").lower() == "true":
                self.createableFields.add(column_name)

        srv_options_for_token = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,
            "password": self.password,
            "login_server": self.login_server,
            "api_version": self.api_version,
            "instance_url": self.instance_url,
            "key_id": self.key_id,
            "provider_org": self.provider_org,
        }

        self.oauth = _get_oauth_token(srv_options_for_token)

        if not self.oauth:
            log_to_postgres("Failed to obtain OAuth token during FDW initialization.", ERROR)

        row_count = options.get("row_count")
        if row_count:
            self.row_count = int(row_count)
        else:
            self.row_count = 10 

    def can_limit(self, limit, offset):
        if self.obj_type == "_bssmagic_table_list":
            return False
        
        if offset is not None and offset > 2000: # Salesforce has a maximum offset of 2000
            return False

        return True

    # Return the sortkeys only up to the first unsortable field
    def can_sort(self, sortkeys):
        if self.obj_type == "_bssmagic_table_list":
            return []
        
        sortable = []
        for sk in sortkeys:
            if getattr(sk, "attname", None) in self.sortableFields:
                sortable.append(sk)
            else:
                break  # Stop at first unsortable field
        return sortable

    #Uses cached record counts to estimate rel size, without applying any filters
    def get_rel_size(self, quals, columns):
        num_columns = max(1, len(columns) if columns is not None else 1)
        return (self.row_count, num_columns * 20)

    def explain(self, quals, columns, sortkeys=None, verbose=False, limit=None, offset=None):
        query = self._build_soql_query(quals, columns, sortkeys, limit, offset)
        return ["salesforce_fdw: %s" % query]

    def execute(self, quals, columns, sortkeys=None, retry=True, limit=None, offset=None):
        
        # If the object type is _bssmagic_table_list, return a list of all the Salesforce objects
        if self.obj_type == "_bssmagic_table_list":
            for obj in _get_sobjects( self.oauth ):
                if obj.get("queryable"):
                    yield {
                        "name": obj.get("name"),
                        "description": obj.get("label"),
                    }
            return
            
        query = self._build_soql_query(quals, columns, sortkeys, limit, offset)
        
        log_to_postgres("FDW generated SOQL query: %s" % query, INFO)

        body = {"query": urllib.parse.quote_plus(query, safe=',')}
        query_url = self.oauth["instance_url"]

        log_to_postgres(f"FDW requesting URL: {query_url}", DEBUG)

        headers = {"Authorization": "Bearer %s" % self.oauth["access_token"], 
                    "Content-Type": "application/json",
                    "KeyId": self.oauth["key_id"],
                    "Timestamp": datetime.now().replace(microsecond=0).isoformat() + "Z",
                    "TransactionId": "API-REST-%s-%s" % (datetime.now().strftime("%d%m%Y"), str(uuid.uuid4())),
                    "ProviderOrgCode": self.oauth["provider_org"]}

        req = urllib.request.Request(query_url, json.dumps(body).encode('utf-8'), headers)

        queue = Queue()

        try:
            log_to_postgres("FDW opening URL request...", DEBUG)
            stream = urllib.request.urlopen(req)
            log_to_postgres("FDW URL request opened successfully.", DEBUG)
        except urllib.error.URLError as e:
            log_to_postgres(
                f"FDW URL Error Code: {e.code if hasattr(e, 'code') else 'N/A'}, Reason: {e.reason if hasattr(e, 'reason') else 'N/A'}",
                ERROR,
            )

            if hasattr(e, "code"):
                if e.code == 401 and retry:
                    log_to_postgres("Invalid token - trying refresh")

                    srv_options_for_refresh = {
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "username": self.username,
                        "password": self.password,
                        "login_server": self.login_server,
                        "api_version": self.api_version,
                    }

                    self.oauth = _get_oauth_token(srv_options_for_refresh)

                    if not self.oauth:
                        log_to_postgres("Failed to refresh OAuth token during execute.", ERROR)

                        return

                    for line in self.execute(quals, columns, False):
                        yield line

                    return
                else:
                    log_to_postgres("HTTP status %d" % e.code, ERROR)
            elif hasattr(e, "reason"):
                log_to_postgres(
                    "Error posting to URL %s: %d %s" % (query_url, e.reason[0], e.reason[1]),
                    ERROR,
                )
            else:
                log_to_postgres("Unknown error %s" % e, ERROR)

            log_to_postgres(f"FDW URL request failed: {e}", ERROR)

            return

        log_to_postgres("FDW starting parse thread...", DEBUG)

        thread_parse_to_queue = Thread(target=parseToQueue, args=(stream, queue, self.column_map))
        thread_parse_to_queue.daemon = True
        thread_parse_to_queue.start()

        log_to_postgres("FDW waiting for item from queue...", DEBUG)

        item = queue.get()

        while item is not None:
            log_to_postgres(f"FDW retrieved item from queue: {item}", DEBUG)
            yield item
            queue.task_done()
            item = queue.get()

        log_to_postgres("FDW finished retrieving items (got None).", DEBUG)
        thread_parse_to_queue.join(timeout=1.0)
        log_to_postgres("FDW execute method finished.", DEBUG)

    def _build_soql_query(self, quals, columns, sortkeys, limit, offset):
        # Sort columns to ensure consistent order
        if columns is None or len(columns) == 0:
            cols = "Id"
        else:   
            # Id is row ID, so it should always be included if the table is writable         
            if self.allow_writes and "Id" not in columns:
                columns = ["Id"] + list(columns)
            cols = ", ".join(sorted(columns))

        where = ""

        for qual in quals:
            if qual.operator in ("~~", "!~~"):
                operator = "LIKE"
            elif qual.operator in ("<", "=", ">", ">=", "<=", "<>"):
                operator = qual.operator
            elif isinstance(qual.operator, tuple):
                operator = qual.operator[0]
                isAny = qual.operator[1]
                if isAny and operator == "=":
                    operator = "IN"
                elif not isAny and operator == "<>":
                    operator = "NOT IN"
                else:
                    log_to_postgres(f"Unsupported {'ANY' if isAny else 'ALL'} operator: {qual.operator}", WARNING)
                    log_to_postgres(f"for values: {qual.value}", WARNING)
                    continue
            elif qual.operator == "IS":
                operator = "="
            elif qual.operator == "IS NOT":
                operator = "<>"
            else:
                log_to_postgres(f"Unsupported operator: {qual.operator}", WARNING)
                continue

            value = qual.value
            if self.columns[qual.field_name].base_type_name == "boolean":
                value = "TRUE" if value == "t" else "FALSE"
            elif ( isinstance(value, str) ):
                if self.columns[qual.field_name].base_type_name == "text":
                    value = "'" + value.replace("'", "''") + "'"
            elif isinstance(value, datetime):
                value = value.isoformat(sep="T", timespec="milliseconds") + "Z"
            elif isinstance(value, list):
                value = str(tuple(value))

            if value is None:
                where += " AND %s %s NULL" % (qual.field_name, operator)
            elif qual.operator == "!~~":
                where += " AND NOT (%s %s %s)" % (qual.field_name, operator, value)
            else:
                where += " AND %s %s %s" % (qual.field_name, operator, value)

        where = where[5:] if where.startswith(" AND ") else where

        query = "SELECT " + cols + " FROM " + self.obj_type

        if len(where) > 0:
            query += " WHERE %s" % where

        if sortkeys is not None:
            order_by = []
            for sortkey in sortkeys:
                order_by.append(f"{sortkey.attname}{sortkey.is_reversed and ' DESC' or ''}{not sortkey.nulls_first and ' NULLS LAST' or ''}")
            query += " ORDER BY %s" % ", ".join(order_by)

        if limit is not None:
            query += " LIMIT %s" % limit

        if offset is not None:
            query += " OFFSET %s" % offset

        return query

    @property
    def rowid_column(self):
        if self.allow_writes:
            return "Id"
        else:
            log_to_postgres( "FDW does not allow writes to this object.", ERROR )

    def _make_request( self, method, url, body=None, retry=True, warnOnly=False ):
        try:
            headers = {"Authorization": "OAuth %s" % self.oauth["access_token"]}
            full_url = f'{self.oauth["instance_url"]}/services/data/{self.api_version}{url}'
            log_to_postgres(f"FDW {method} to URL: {full_url}", DEBUG)
            response = requests.request(
                method=method,
                url=full_url,
                json=body,
                headers=headers,
                timeout=30,
            )

            if response.status_code == 401 and retry:
                log_to_postgres("Invalid token - trying refresh", WARNING)
                srv_options_for_refresh = {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "username": self.username,
                    "password": self.password,
                    "login_server": self.login_server,
                    "api_version": self.api_version,
                }
                self.oauth = _get_oauth_token(srv_options_for_refresh)

                if not self.oauth:
                    log_to_postgres("Failed to refresh OAuth token during execute.", ERROR)

                return self._make_request(method, url, body, False)

            response.raise_for_status()
            if not response.text:
                return None
            return response.json()
        except requests.RequestException as e:
            log_to_postgres(f"Salesforce API request failed: {str(e)}, {response.text}", ERROR if not warnOnly else WARNING)

    def _get_axway_headers(self):
        """Build standard Axway request headers (auth + tracing)."""
        return {
            "Authorization": "Bearer %s" % self.oauth["access_token"],
            "Content-Type": "application/json",
            "KeyId": self.oauth.get("key_id", ""),
            "Timestamp": datetime.now().replace(microsecond=0).isoformat() + "Z",
            "TransactionId": "API-REST-%s-%s" % (datetime.now().strftime("%d%m%Y"), str(uuid.uuid4())),
            "ProviderOrgCode": self.oauth.get("provider_org", ""),
        }

    def _axway_insert(self, values, retry=True):
        """
        Route an INSERT through the Axway proxy.

        Translates Salesforce field names to Axway field names, POSTs to the
        object-specific Axway endpoint, and returns a dict with Salesforce
        column names so that multicorn can return the new row.
        """
        config = AXWAY_WRITE_CONFIG[self.obj_type]
        field_map = config['field_map']

        # Map Salesforce field names -> Axway field names
        axway_payload = {}
        for sf_field, value in values.items():
            if sf_field in field_map:
                axway_payload[field_map[sf_field]] = value
            elif sf_field == 'Id':
                # Id is auto-included by the FDW for writable tables; skip it on create
                continue
            else:
                log_to_postgres(
                    f"Axway INSERT: unmapped field '{sf_field}' for {self.obj_type} -- sending as-is",
                    WARNING,
                )
                axway_payload[sf_field] = value

        headers = self._get_axway_headers()
        endpoint = config['url']

        log_to_postgres(
            f"FDW Axway INSERT {self.obj_type} -> {endpoint} "
            f"({len(axway_payload)} fields)",
            INFO,
        )
        log_to_postgres(f"Axway payload: {axway_payload}", DEBUG)

        try:
            response = requests.post(
                endpoint,
                json=axway_payload,
                headers=headers,
                timeout=30,
            )

            # Token expired -- refresh once and retry
            if response.status_code == 401 and retry:
                log_to_postgres("Axway token expired during write -- refreshing", WARNING)
                srv_options = {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "username": self.username,
                    "password": self.password,
                    "login_server": self.login_server,
                    "api_version": self.api_version,
                    "instance_url": self.instance_url,
                    "key_id": self.key_id,
                    "provider_org": self.provider_org,
                }
                self.oauth = _get_oauth_token(srv_options)
                if not self.oauth:
                    log_to_postgres("Failed to refresh OAuth token for Axway write.", ERROR)
                return self._axway_insert(values, retry=False)

            if response.status_code not in (200, 201):
                log_to_postgres(
                    f"Axway {self.obj_type} write failed "
                    f"(HTTP {response.status_code}): {response.text}",
                    ERROR,
                )

            # Parse response and reverse-map Axway field names -> Salesforce names
            result = {}
            if response.text:
                try:
                    axway_response = response.json()
                except (json.JSONDecodeError, ValueError):
                    axway_response = {}

                reverse_map = AXWAY_REVERSE_FIELD_MAPS.get(self.obj_type, {})
                if isinstance(axway_response, dict):
                    for key, value in axway_response.items():
                        sf_key = reverse_map.get(key, key)
                        if sf_key in self.columns:
                            result[sf_key] = value

            log_to_postgres(f"Axway INSERT response mapped to {len(result)} SF fields", DEBUG)

            # Merge original values so multicorn has a complete row for RETURNING
            merged = dict(values)
            merged.update(result)
            return merged

        except requests.RequestException as e:
            log_to_postgres(
                f"Axway write request to {endpoint} failed: {str(e)}", ERROR
            )

    def insert(self, values):
        if not self.allow_writes:
            log_to_postgres("FDW does not allow writes to this object.", ERROR)

        # Remove null values
        values = {field: val for field, val in values.items() if val is not None}

        # Serialize Dates/Times as ISO 8601 strings
        for field, value in values.items():
            if isinstance(value, datetime):
                column = self.columns.get(field)
                if column and column.type_name.lower() == "date":
                    values[field] = value.date().isoformat()
                else:
                    values[field] = value.isoformat(sep="T", timespec="milliseconds") + "Z"

        # Convert bytes → str (bytea columns like VersionData arrive as bytes;
        # Axway expects base64 text in JSON, not raw bytes)
        for field, value in values.items():
            if isinstance(value, (bytes, bytearray)):
                values[field] = value.decode('utf-8', errors='replace')

        # --- Axway proxy routing ---
        # Objects in AXWAY_WRITE_CONFIG are routed to dedicated Axway endpoints
        # with field-name translation. All other objects are unsupported for
        # writes in Phase 2 (instance_url is Axway, not Salesforce).
        if self.obj_type in AXWAY_WRITE_CONFIG:
            return self._axway_insert(values)

        # For objects NOT in the Axway write config, the Composite API path
        # won't work because instance_url now points to the Axway query endpoint.
        # Raise a clear error instead of producing a cryptic HTTP failure.
        log_to_postgres(
            f"Write to '{self.obj_type}' is not supported through the Axway proxy. "
            f"Supported writable objects: {list(AXWAY_WRITE_CONFIG.keys())}",
            ERROR,
        )


    def update(self, rowid, newvalues):
        if not self.allow_writes:
            log_to_postgres( "FDW does not allow writes to this object.", ERROR )
        
        # Check for any fields in newvalues that are not updateable
        not_updateable = [field for field in newvalues if field not in self.updateableFields]
        if not_updateable:
            for field in not_updateable:
                newvalues.pop(field, None)
        
        # Check if any required fields are set to null
        null_required = [field for field, value in newvalues.items() if value is None and field not in self.nillableFields]
        if null_required:
            log_to_postgres( f"Non-nullable fields set to null for Salesforce update: {null_required}", ERROR )

        # Serialize Dates/Times as ISO 8601 strings
        for field, value in newvalues.items():
            if isinstance(value, datetime):
                column = self.columns.get(field)
                if column and column.type_name.lower() == "date":
                    newvalues[field] = value.date().isoformat()
                else:
                    newvalues[field] = value.isoformat(sep="T", timespec="milliseconds") + "Z"

        composite_request = {
            "allOrNone": False,
            "compositeRequest": [
                {
                    "method": "PATCH",
                    "url": f"/services/data/{self.api_version}/sobjects/{self.obj_type}/{rowid}",
                    "referenceId": "updateAccount",
                    "body": newvalues
                },
                {
                    "method": "GET",
                    "url": f"/services/data/{self.api_version}/sobjects/{self.obj_type}/{rowid}",
                    "referenceId": "getAccount"
                }
            ]
        }  

        response = self._make_request("POST", f"/composite", composite_request)
        if response['compositeResponse'][0]['httpStatusCode'] != 204:
            if isinstance(response['compositeResponse'][0]['body'], dict) and 'errors' in response['compositeResponse'][0]['body']:
                log_to_postgres(f"Salesforce API request failed with {response['compositeResponse'][0]['httpStatusCode']}: {response['compositeResponse'][0]['body']['errors']}", ERROR)
            else:
                log_to_postgres(f"Salesforce API request failed with {response['compositeResponse'][0]['httpStatusCode']}: {response['compositeResponse'][0]['body']}", ERROR)
        
        return response['compositeResponse'][1]['body']


    def delete(self, rowid):
        if not self.allow_writes:
            log_to_postgres( "FDW does not allow writes to this object.", ERROR )

        response = self._make_request("DELETE", f"/sobjects/{self.obj_type}/{rowid}")


    @classmethod
    def import_schema(cls, schema, srv_options, options, restriction_type, restricts):
        return []       
