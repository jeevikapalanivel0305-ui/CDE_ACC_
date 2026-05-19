"""
Microsoft Fabric Connector
- Authentication via Azure AD
- Fabric Item discovery (Workspaces -> Items)
- Maps Fabric Items to CDEs

Author: Jeevika
"""

import requests
import socket
import json
import pyodbc
import pandas as pd

class FabricConnector:
    def __init__(self, tenant_id, client_id, client_secret):
        self.tenant_id = tenant_id.strip()
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.token = None
        self.base_url = "https://api.fabric.microsoft.com/v1"

    # =========================================================
    # AUTHENTICATION
    # =========================================================
    def authenticate(self, debug=False):
        """Authenticate with Azure AD for Fabric"""
        try:
            url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
            
            # Fabric scope
            scope = "https://api.fabric.microsoft.com/.default"
            
            payload = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": scope
            }

            if debug:
                print(f"Authenticating to Azure AD for tenant: {self.tenant_id}")

            resp = requests.post(url, data=payload, timeout=30)

            if resp.status_code != 200:
                error_detail = resp.json().get('error_description', resp.text)
                if "AADSTS700016" in error_detail:
                    return False, f"Error: Application (Client ID) not found in this Tenant. Please check that you are using the correct Tenant ID and Client ID pair. \nDataset: {error_detail}"
                return False, f"Authentication failed (HTTP {resp.status_code}): {error_detail}"

            self.token = resp.json().get("access_token")
            
            if not self.token:
                 return False, "Authentication failed: No access token received"

            if debug:
                print("✅ Authentication successful")

            return True, "Authenticated successfully"
        
        except requests.exceptions.RequestException as e:
            return False, f"Authentication request failed: {str(e)}"
        except Exception as e:
            return False, f"Unexpected authentication error: {str(e)}"

    def _headers(self):
        """Get authorization headers"""
        if not self.token:
            raise Exception("Not authenticated. Call authenticate() first")
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    # =========================================================
    # REST API — WORKSPACE / ITEM BROWSER
    # =========================================================
    def _ensure_token(self):
        if not self.token:
            ok, msg = self.authenticate()
            if not ok:
                raise Exception(f"Authentication failed: {msg}")

    def list_workspaces(self):
        """Return list of dicts with 'id' and 'displayName' for all accessible workspaces."""
        self._ensure_token()
        resp = requests.get(f"{self.base_url}/workspaces", headers=self._headers(), timeout=30)
        if resp.status_code == 200:
            return resp.json().get("value", [])
        raise Exception(f"Could not list workspaces ({resp.status_code}): {resp.json().get('message', resp.text)}")

    def list_items(self, workspace_id: str, item_type: str):
        """Return list of dicts with 'id' and 'displayName' for Lakehouses or Warehouses in a workspace.
        item_type: 'Lakehouse' or 'Warehouse'
        """
        self._ensure_token()
        url = f"{self.base_url}/workspaces/{workspace_id}/items?type={item_type}"
        resp = requests.get(url, headers=self._headers(), timeout=30)
        if resp.status_code == 200:
            return resp.json().get("value", [])
        raise Exception(f"Could not list {item_type}s ({resp.status_code}): {resp.json().get('message', resp.text)}")

    # =========================================================
    # REST API — TABLE LISTING
    # =========================================================
    def list_tables_via_api(self, workspace_id: str, item_id: str, item_type: str = "lakehouse"):
        """List tables from a Fabric item using the REST API.
        Lakehouse: uses the dedicated /tables endpoint.
        Warehouse: executes INFORMATION_SCHEMA query via the Fabric query endpoint.
        """
        self._ensure_token()
        workspace_id = workspace_id.strip()
        item_id = item_id.strip()

        if item_type.lower() == "lakehouse":
            url = f"{self.base_url}/workspaces/{workspace_id}/lakehouses/{item_id}/tables"
            resp = requests.get(url, headers=self._headers(), timeout=30)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                return [t["name"] for t in data if t.get("name")]
            raise Exception(f"REST API error {resp.status_code}: {resp.json().get('message', resp.text)}")

        if item_type.lower() == "warehouse":
            # Execute a lightweight INFORMATION_SCHEMA query via the Fabric execute-query API
            url = f"{self.base_url}/workspaces/{workspace_id}/warehouses/{item_id}/tables"
            resp = requests.get(url, headers=self._headers(), timeout=30)
            if resp.status_code == 200:
                data = resp.json().get("data", resp.json().get("value", []))
                if data:
                    return [t.get("name") or t.get("displayName", "") for t in data if t.get("name") or t.get("displayName")]
            # If the /tables endpoint is not available, tell the caller
            raise Exception(
                f"Fabric REST API does not expose warehouse table listing "
                f"(status {resp.status_code}). Please enter the table name manually below."
            )

        raise Exception(f"Unsupported item type: {item_type}")

    # =========================================================
    # FETCH FABRIC ITEMS (Simulated/Real)
    # =========================================================
    def fetch_cdes(self, debug=False):
        """
        Fetch 'CDEs' from Fabric.

        Since Fabric doesn't have a direct 'CDE' concept like Purview's Data Governance yet,
        we will map Fabric Items (Lakehouses, Warehouses, Datasets) as potential CDEs.
        """
        # Ensure authenticated
        if not self.token:
             success, msg = self.authenticate(debug)
             if not success:
                 raise Exception(msg)

        try:
            # ---------------------------------------------------------
            # REAL API CALL (if permissions allow)
            # ---------------------------------------------------------
            # url = f"{self.base_url}/workspaces"
            # r = requests.get(url, headers=self._headers(), timeout=30)
            # if r.status_code == 200:
            #     workspaces = r.json().get('value', [])
            #     # ... iterate workspaces and get items ...
            # ---------------------------------------------------------
            
            # ---------------------------------------------------------
            # SIMULATION / MOCK DATA
            # (For demonstration until Service Principal has correct Fabric Admin scopes)
            # ---------------------------------------------------------
            if debug:
                print("⚠️ Using Simulated Fabric Data for demonstration (API might require Admin consent)")
            
            # Simulated Fabric Items
            fabric_items = [
                {
                    "id": "fab-001",
                    "displayName": "Sales_Gold_Lakehouse",
                    "type": "Lakehouse",
                    "workspaceId": "ws-sales-01", 
                    "workspaceName": "Sales Analytics",
                    "description": "Gold layer data for sales reporting. Contains validated transaction records."
                },
                {
                    "id": "fab-002",
                    "displayName": "Customer_360_Dataset",
                    "type": "SemanticModel",
                    "workspaceId": "ws-marketing-01",
                    "workspaceName": "Marketing Ops",
                    "description": "Unified customer view including demographics and behavioral data."
                },
                {
                    "id": "fab-003",
                    "displayName": "Finance_GL_Warehouse",
                    "type": "Warehouse",
                    "workspaceId": "ws-finance-01",
                    "workspaceName": "Finance & Risk",
                    "description": "General Ledger data for monthly financial reporting."
                },
                {
                    "id": "fab-004",
                    "displayName": "Raw_IoT_Telemetry",
                    "type": "KQLDatabase",
                    "workspaceId": "ws-ops-01",
                    "workspaceName": "Operations",
                    "description": "Real-time telemetry from manufacturing sensors."
                },
                {
                     "id": "fab-005",
                     "displayName": "HR_Employee_Master",
                     "type": "Lakehouse",
                     "workspaceId": "ws-hr-01",
                     "workspaceName": "Human Resources",
                     "description": "Master employee records including sensitive PII."
                }
            ]
            
            cdes = []
            for item in fabric_items:
                cdes.append(self._map_to_cde(item))
                
            return cdes

        except Exception as e:
            raise Exception(f"Failed to fetch Fabric items: {str(e)}")

    def _clean_html(self, text):
        """Remove HTML tags from text"""
        if not text:
            return ""
        import re
        clean = re.compile('<.*?>')
        return re.sub(clean, '', str(text))

    def _map_to_cde(self, item):
        """Map Fabric Item to CDE schema"""
        # Determine domain from workspace name if possible
        domain = "Reference"
        
        # Combine workspace name and item name for better context
        text = (str(item.get('workspaceName', '')) + " " + str(item.get('displayName', ''))).lower()
        
        keywords = {
            'Healthcare': ['patient', 'doctor', 'hospital', 'medical', 'drug', 'treatment', 'diagnosis', 'clinical', 'provider', 'health'],
            'Finance / Banking': ['account', 'bank', 'credit', 'tax', 'transaction', 'payment', 'balance', 'loan', 'gl', 'ledger', 'financial', 'finance', 'wealth'],
            'Retail / E-Commerce': ['customer', 'product', 'order', 'sale', 'store', 'inventory', 'price', 'item', 'sku', 'market', 'shop', 'cart', 'merchant'],
            'Insurance': ['policy', 'claim', 'premium', 'coverage', 'underwriter', 'risk'],
            'Manufacturing': ['plant', 'factory', 'machine', 'production', 'assembly', 'supply', 'material', 'ops', 'operations'],
            'Energy / Utilities': ['grid', 'power', 'oil', 'gas', 'renewable', 'utility', 'energy', 'electric', 'water'],
            'Government': ['citizen', 'regulation', 'law', 'compliance', 'agency', 'gov', 'public'],
            'General': ['reference', 'master', 'dimension', 'lookup', 'code', 'common', 'shared']
        }
        
        domain_found = False
        for d, keys in keywords.items():
            for key in keys:
                if key in text:
                    domain = d
                    domain_found = True
                    break
            if domain_found:
                break
        
        return {
            "id": None, # Will be assigned on import
            "name": item.get("displayName", "Unnamed Fabric Item"),
            "description": self._clean_html(item.get("description", "")),
            "definition": self._clean_html(item.get("description", "")),
            "domain": domain,
            "status": "Active",
            "owner": "Fabric Admin", # Placeholder
            "steward": "Workspace Admin", # Placeholder
            "sourceSystem": "Microsoft Fabric",
            "dataType": item.get("type", "Unknown"), # e.g. Lakehouse, Warehouse
            # Default risk scores
            "businessImpact": 3,
            "regulatoryCompliance": 3,
            "dataQualityRisk": 3,
            "securityRisk": 3,
            "systemComplexity": 3,
            "recoveryDifficulty": 3,
            "downstreamSystems": "",
            "regulatory": "",
            "assessmentDate": "",
            "notes": f"Imported from Fabric Workspace: {item.get('workspaceName')}"
        }

    # =========================================================
    # SQL ENDPOINT INTEGRATION (Hybrid Mode)
    # =========================================================
    def _get_sql_access_token(self):
        """Get an access token scoped for Azure SQL / Fabric SQL endpoints."""
        try:
            url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
            payload = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://database.windows.net/.default",
            }
            resp = requests.post(url, data=payload, timeout=30)
            if resp.status_code == 200:
                return resp.json().get("access_token"), None
            return None, resp.json().get("error_description", resp.text)
        except Exception as e:
            return None, str(e)

    def get_sql_connection(self, connection_string, database_name=None):
        """Create a pyodbc connection to Fabric SQL Endpoint using access-token auth."""
        import struct

        try:
            # Clean the endpoint string
            raw_endpoint = str(connection_string).strip()
            for prefix in ("https://", "tcp:"):
                if raw_endpoint.startswith(prefix):
                    raw_endpoint = raw_endpoint[len(prefix):]

            if "api.fabric.microsoft.com" in raw_endpoint.lower():
                raise Exception(
                    "The URL looks like a Fabric REST API URL. "
                    "Please use the SQL Analytics Endpoint "
                    "(e.g. xxxxxxxx-xxxx.datawarehouse.fabric.microsoft.com)."
                )

            # Find the best available ODBC driver
            drivers = pyodbc.drivers()
            best_driver = next(
                (d for d in ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"] if d in drivers),
                None,
            )
            if not best_driver:
                raise Exception(
                    "No compatible ODBC driver found. "
                    "Install 'ODBC Driver 18 for SQL Server' on the host."
                )

            server_name = raw_endpoint.split(";")[0]
            if "," not in server_name:
                server_name += ",1433"

            odbc_str = (
                f"DRIVER={{{best_driver}}};"
                f"SERVER={server_name};"
                "Encrypt=yes;"
                "TrustServerCertificate=no;"
            )
            if database_name:
                odbc_str += f"DATABASE={database_name};"

            print(f"[SQL] Connecting to {server_name} db={database_name or 'default'} driver={best_driver}")

            # ── Preferred: access-token auth (avoids MSAL/ADAL dependency) ──────
            if self.tenant_id and self.client_id and self.client_secret:
                sql_token, err = self._get_sql_access_token()
                if sql_token:
                    token_enc = sql_token.encode("utf-16-le")
                    token_struct = struct.pack(f"<I{len(token_enc)}s", len(token_enc), token_enc)
                    attrs_before = {1256: token_struct}  # SQL_COPT_SS_ACCESS_TOKEN
                    print("[SQL] Using access-token authentication.")
                    conn = pyodbc.connect(odbc_str, attrs_before=attrs_before, timeout=30)
                    print("[SQL] Connection successful.")
                    return conn
                else:
                    print(f"[SQL] Access-token fetch failed ({err}). Falling back to credential auth.")
                    # Fallback: embed credentials directly
                    odbc_str += f"UID={self.client_id};PWD={self.client_secret};Authentication=ActiveDirectoryServicePrincipal;"
            elif self.client_id and self.client_secret:
                # No tenant ID — try credential auth anyway
                odbc_str += f"UID={self.client_id};PWD={self.client_secret};Authentication=ActiveDirectoryServicePrincipal;"
            else:
                raise Exception(
                    "No credentials configured. "
                    "Please enter Tenant ID, Client ID, and Client Secret in the Fabric Connector settings."
                )

            # 5. Connect
            conn = pyodbc.connect(odbc_str, timeout=30)
            print("🔗 [SQL] Connection successful.")
            return conn
        except Exception as e:
            print(f"❌ [SQL] Connection error: {str(e)}")
            raise e

    def list_tables(self, connection_string, database_name=None):
        """List all user tables in the Fabric SQL Endpoint"""
        conn = None
        try:
            conn = self.get_sql_connection(connection_string, database_name)
            cursor = conn.cursor()
            # Query for user tables
            cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'")
            tables = [row[0] for row in cursor.fetchall()]
            return tables
        except Exception as e:
            raise Exception(f"Failed to list tables: {str(e)}")
        finally:
            if conn: conn.close()

    def fetch_table_schema(self, connection_string, table_name, database_name=None):
        """Fetch column names and types from a Fabric table"""
        conn = None
        try:
            conn = self.get_sql_connection(connection_string, database_name)
            cursor = conn.cursor()
            
            # Extract schema and table name if provided as schema.table
            target_schema = 'dbo'
            target_table = table_name
            if '.' in table_name:
                parts = table_name.split('.')
                target_schema = parts[0]
                target_table = parts[1]

            # Use INFORMATION_SCHEMA for portability
            query = f"""
            SELECT COLUMN_NAME, DATA_TYPE 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_NAME = '{target_table}'
            AND TABLE_SCHEMA = '{target_schema}'
            """
            cursor.execute(query)
            columns = [{"name": row[0], "type": row[1]} for row in cursor.fetchall()]
            
            if not columns:
                # Fallback: try just table name if schema match fails
                cursor.execute(f"SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = '{table_name}'")
                columns = [{"name": row[0], "type": row[1]} for row in cursor.fetchall()]
                
            if not columns:
                raise Exception(f"Table '{table_name}' not found or has no columns in database '{database_name or 'default'}'.")
                
            return columns
        finally:
            if conn:
                conn.close()

    def sync_to_fabric(self, df, connection_string, table_name, database_name=None, create_if_not_exists=True):
        """Append CDE Register data to a Fabric table, with optimized batch insertion"""
        conn = None
        try:
            # Prepare data (select relevant columns)
            cols = ['id', 'name', 'domain', 'definition', 'sourceSystem', 'businessImpact', 'regulatoryCompliance', 'dataQualityRisk']
            for col in cols:
                if col not in df.columns: df[col] = ""
            
            # Clean and format data for SQL
            df_sync = df[cols].copy()
            for col in ['businessImpact', 'regulatoryCompliance', 'dataQualityRisk']:
                df_sync[col] = pd.to_numeric(df_sync[col], errors='coerce').fillna(3).astype(int)
            df_sync = df_sync.fillna("")
            
            # Ensure schema prefix if missing
            if "." not in table_name:
                table_name = f"dbo.{table_name}"
            
            conn = self.get_sql_connection(connection_string, database_name)
            cursor = conn.cursor()
            
            # Step 1: Create table if needed
            if create_if_not_exists:
                print(f"🛠️ [SQL] Preparing table '{table_name}'...")
                cursor.execute(f"""
                    IF OBJECT_ID('{table_name}', 'U') IS NULL 
                    CREATE TABLE {table_name} (
                        id VARCHAR(50), 
                        name VARCHAR(255), 
                        domain VARCHAR(100), 
                        definition VARCHAR(8000), 
                        sourceSystem VARCHAR(100), 
                        businessImpact INT, 
                        regulatoryCompliance INT, 
                        dataQualityRisk INT
                    )
                """)
                conn.commit()
            
            # Step 2: Batch Insert
            data_to_insert = [tuple(x) for x in df_sync.values]
            query = f"INSERT INTO {table_name} (id, name, domain, definition, sourceSystem, businessImpact, regulatoryCompliance, dataQualityRisk) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            
            print(f"🚀 [SQL] Syncing {len(data_to_insert)} records to {table_name}...")
            
            # Performance optimization: enable fast_executemany
            cursor.fast_executemany = True
            cursor.executemany(query, data_to_insert)
            
            conn.commit()
            print(f"✅ [SQL] Sync complete for {table_name}.")
            return True, f"Successfully synced {len(data_to_insert)} records to '{table_name}'."
        except Exception as e:
            print(f"❌ [SQL] Sync error: {str(e)}")
            if conn: conn.rollback()
            return False, f"Sync failed: {str(e)}"
        finally:
            if conn: conn.close()
