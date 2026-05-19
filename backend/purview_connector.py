"""
Microsoft Purview Connector with Enhanced Error Handling
- Authentication
- Catalog asset discovery (Datamap / Atlas)
- Critical Data Element (CDE) discovery (Data Governance)

Author: Jeevika
"""

import requests
import socket


class PurviewConnector:
    def __init__(self, account_name, tenant_id, client_id, client_secret):
        self.account_name = account_name.strip()
        self.tenant_id = tenant_id.strip()
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()

        self.token = None
        self.base_url = f"https://{self.account_name}.purview.azure.com"
        self.hostname = f"{self.account_name}.purview.azure.com"

    # =========================================================
    # DNS AND NETWORK VALIDATION
    # =========================================================
    def validate_network(self):
        """Validate DNS resolution and network connectivity"""
        try:
            # Try to resolve the hostname
            socket.gethostbyname(self.hostname)
            return True, f"DNS resolution successful for {self.hostname}"
        except socket.gaierror as e:
            return False, f"DNS resolution failed for {self.hostname}. Error: {str(e)}"
        except Exception as e:
            return False, f"Network validation failed: {str(e)}"

    def validate_account_name(self):
        """Validate Purview account name format"""
        if not self.account_name:
            return False, "Purview account name is empty"
        
        # Account name should be lowercase alphanumeric and hyphens only
        if not self.account_name.replace('-', '').isalnum():
            return False, "Invalid account name format. Use only lowercase letters, numbers, and hyphens"
        
        if len(self.account_name) < 3 or len(self.account_name) > 63:
            return False, "Account name must be between 3 and 63 characters"
        
        return True, "Account name format is valid"

    # =========================================================
    # AUTHENTICATION
    # =========================================================
    def authenticate(self, debug=False):
        """Authenticate with Azure AD"""
        # First validate account name
        valid, msg = self.validate_account_name()
        if not valid:
            return False, f"Account validation failed: {msg}"
        
        # Then check network connectivity
        valid, msg = self.validate_network()
        if not valid:
            return False, f"Network validation failed: {msg}. Please check:\n1. Purview account name is correct\n2. You have internet connectivity\n3. DNS can resolve Azure domains\n4. VPN/Firewall is not blocking access"
        
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"

        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://purview.azure.net/.default"
        }

        if debug:
            print(f"Authenticating to Azure AD for tenant: {self.tenant_id}")
            print(f"Target Purview account: {self.account_name}")

        try:
            resp = requests.post(url, data=payload, timeout=30)

            if resp.status_code != 200:
                error_detail = resp.json().get('error_description', resp.text)
                if "AADSTS700016" in error_detail:
                    return False, f"Error: Application (Client ID) not found in this Tenant. Please check that you are using the correct Tenant ID and Client ID pair. \nDataset: {error_detail}"
                return False, f"Authentication failed (HTTP {resp.status_code}): {error_detail}"

            self.token = resp.json()["access_token"]

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
    # TEST CONNECTION
    # =========================================================
    def test_connection(self, debug=False):
        """Test connection to Purview with comprehensive validation"""
        stats = {}
        
        # Step 1: Validate account name
        valid, msg = self.validate_account_name()
        stats['account_validation'] = 'OK' if valid else f'FAILED: {msg}'
        if not valid:
            return False, msg, stats
        
        # Step 2: Validate network
        valid, msg = self.validate_network()
        stats['network_validation'] = 'OK' if valid else f'FAILED: {msg}'
        if not valid:
            return False, msg, stats
        
        # Step 3: Authenticate
        success, msg = self.authenticate(debug=debug)
        stats['authentication'] = 'OK' if success else f'FAILED: {msg}'
        if not success:
            return False, msg, stats

        # Step 4: Test Catalog API
        try:
            url = f"{self.base_url}/datamap/api/search/query"
            params = {"api-version": "2023-09-01"}
            payload = {"keywords": "*", "limit": 1}

            r = requests.post(
                url,
                headers=self._headers(),
                params=params,
                json=payload,
                timeout=30
            )

            if r.status_code == 200:
                stats["catalog_access"] = "OK"
                stats["sample_assets"] = len(r.json().get("value", []))
            else:
                stats["catalog_error"] = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            stats["catalog_error"] = str(e)

        # Step 5: Test CDE API
        try:
            url = f"{self.base_url}/datagovernance/catalog/criticalDataElements"
            params = {"api-version": "2025-09-15-preview"}

            r = requests.get(
                url,
                headers=self._headers(),
                params=params,
                timeout=30
            )

            if r.status_code == 200:
                cde_data = r.json()
                stats["cde_count"] = len(cde_data.get("value", []))
                stats["cde_access"] = "OK"
            elif r.status_code == 404:
                stats["cde_error"] = "CDE API endpoint not found (404). This Purview instance may not have Data Governance enabled"
            else:
                stats["cde_error"] = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            stats["cde_error"] = str(e)

        return True, "Connection test completed", stats

    # =========================================================
    # SEARCH CATALOG ASSETS
    # =========================================================
    def search_assets(self, limit=100, debug=False):
        """Search catalog assets"""
        success, msg = self.authenticate(debug=debug)
        if not success:
            raise Exception(msg)

        url = f"{self.base_url}/datamap/api/search/query"
        params = {"api-version": "2023-09-01"}
        payload = {"keywords": "*", "limit": limit}

        try:
            r = requests.post(
                url,
                headers=self._headers(),
                params=params,
                json=payload,
                timeout=30
            )

            if r.status_code != 200:
                raise Exception(f"Search failed (HTTP {r.status_code}): {r.text}")

            return r.json().get("value", [])
        
        except requests.exceptions.RequestException as e:
            raise Exception(f"Search request failed: {str(e)}")

    # =========================================================
    # GET ENTITY BY GUID
    # =========================================================
    def get_entity(self, guid, debug=False):
        """Get entity details by GUID — requests full relationship data"""
        success, msg = self.authenticate(debug=debug)
        if not success:
            raise Exception(msg)

        url = f"{self.base_url}/datamap/api/atlas/v2/entity/guid/{guid}"
        params = {
            "api-version": "2023-09-01",
            "minExtInfo": "true",
            "ignoreRelationships": "false"
        }

        try:
            r = requests.get(
                url,
                headers=self._headers(),
                params=params,
                timeout=30
            )

            return r.json() if r.status_code == 200 else None
        
        except requests.exceptions.RequestException as e:
            raise Exception(f"Get entity failed: {str(e)}")

    # =========================================================
    # FETCH CRITICAL DATA ELEMENTS
    # =========================================================
    def fetch_cdes(self, debug=False):
        """Fetch Critical Data Elements from Purview Data Governance"""
        success, msg = self.authenticate(debug=debug)
        if not success:
            raise Exception(f"Authentication failed: {msg}")

        url = f"{self.base_url}/datagovernance/catalog/criticalDataElements"
        params = {"api-version": "2025-09-15-preview"}

        if debug:
            print(f"Fetching CDEs from: {url}")
            print(f"Parameters: {params}")

        try:
            r = requests.get(
                url,
                headers=self._headers(),
                params=params,
                timeout=30
            )

            if debug:
                print(f"Response status: {r.status_code}")
                print(f"Response headers: {dict(r.headers)}")
                print(f"Response body (first 500 chars): {r.text[:500]}")

            if r.status_code == 404:
                raise Exception("CDE API endpoint not found (404). This Purview instance may not have Data Governance enabled or the API version may be incorrect")
            
            if r.status_code != 200:
                raise Exception(f"Failed to fetch CDEs (HTTP {r.status_code}): {r.text[:500]}")

            cdes = []
            response_data = r.json()
            
            if debug:
                print(f"Response data keys: {response_data.keys()}")
                print(f"Number of CDEs found: {len(response_data.get('value', []))}")
            
            for item in response_data.get("value", []):
                if isinstance(item, dict):
                    cdes.append(self._map_cde(item))
                else:
                    cdes.append({
                        "id": None,
                        "name": str(item),
                        "description": "",
                        "domain": "Reference",
                        "status": "Active",
                        "owner": None,
                        "steward": None,
                        "sourceSystem": "Purview"
                    })

            return cdes
        
        except requests.exceptions.ConnectionError as e:
            raise Exception(f"Connection error: {str(e)}. Please check:\n1. Purview account name is correct\n2. Network connectivity to Azure\n3. VPN/Firewall settings")
        except requests.exceptions.Timeout as e:
            raise Exception(f"Request timeout: {str(e)}. The Purview service may be slow or unavailable")
        except requests.exceptions.RequestException as e:
            raise Exception(f"Request failed: {str(e)}")

    # =========================================================
    # SAFE CDE MAPPING
    # =========================================================
    def _map_cde(self, cde):
        """Map Purview CDE to standard format"""
        domain = cde.get("domain")

        domain_id   = ""
        domain_name = ""
        if isinstance(domain, dict):
            domain_id   = domain.get("id", "")
            domain_name = domain.get("name") or domain.get("displayName") or ""
            if not domain_name:
                domain_name = self._infer_domain(cde.get("name"), cde.get("description"))
        elif isinstance(domain, str):
            if len(domain) == 36 and '-' in domain:
                domain_id   = domain
                domain_name = self._infer_domain(cde.get("name"), cde.get("description"))
            else:
                domain_name = domain
        else:
            domain_name = self._infer_domain(cde.get("name"), cde.get("description"))

        return {
            "id": cde.get("id"),
            "name": cde.get("name", "Unnamed CDE"),
            "description": self._clean_html(cde.get("description", "")),
            "definition": self._clean_html(cde.get("description", "")),
            "domain": domain_name,
            "domain_id": domain_id,        # preserved so UI can use it for domain selection
            "status": cde.get("status", "Active"),
            "owner": self._get_contact(cde, "owners"),
            "steward": self._get_contact(cde, "dataStewards"),
            "sourceSystem": "Purview",
            "businessImpact": 3,
            "regulatoryCompliance": 3,
            "dataQualityRisk": 3,
            "securityRisk": 3,
            "systemComplexity": 3,
            "recoveryDifficulty": 3,
            "dataType": cde.get("dataType", ""),
            "downstreamSystems": "",
            "regulatory": "",
            "assessmentDate": "",
            "notes": "Imported from Microsoft Purview"
        }

    def _clean_html(self, text):
        """Remove HTML tags from text"""
        if not text:
            return ""
        import re
        clean = re.compile('<.*?>')
        return re.sub(clean, '', str(text))

    def _infer_domain(self, name, description):
        """Infer domain based on keywords in name and description"""
        text = (str(name) + " " + str(description)).lower()
        
        keywords = {
            'Healthcare': ['patient', 'doctor', 'hospital', 'medical', 'drug', 'treatment', 'diagnosis', 'clinical', 'provider', 'health'],
            'Finance / Banking': ['account', 'bank', 'credit', 'tax', 'transaction', 'payment', 'balance', 'loan', 'gl', 'ledger', 'financial', 'finance', 'wealth'],
            'Retail / E-Commerce': ['customer', 'product', 'order', 'sale', 'store', 'inventory', 'price', 'item', 'sku', 'market', 'shop', 'cart', 'merchant'],
            'Insurance': ['policy', 'claim', 'premium', 'coverage', 'underwriter', 'risk'],
            'Manufacturing': ['plant', 'factory', 'machine', 'production', 'assembly', 'supply', 'material'],
            'Energy / Utilities': ['grid', 'power', 'oil', 'gas', 'renewable', 'utility', 'energy', 'electric', 'water'],
            'Government': ['citizen', 'regulation', 'law', 'compliance', 'agency', 'gov', 'public'],
            'General': ['reference', 'master', 'dimension', 'lookup', 'code', 'common']
        }
        
        for domain, keys in keywords.items():
            for key in keys:
                if key in text:
                    return domain
                    
        return "General"

    def _get_contact(self, cde, role):
        """Safely extract contact information"""
        try:
            contacts = cde.get("contacts", {}).get(role, [])
            if isinstance(contacts, list) and contacts:
                contact = contacts[0]
                if isinstance(contact, dict):
                    return contact.get("displayName") or contact.get("name") or contact.get("email")
                return str(contact)
            return None
        except Exception:
            return None

    # =========================================================
    # SEARCH TABLE ASSETS IN CATALOG
    # =========================================================
    def search_tables(self, keyword="*", limit=100, debug=False):
        """Search for table-type assets in the Purview catalog"""
        success, msg = self.authenticate(debug=debug)
        if not success:
            raise Exception(msg)

        url = f"{self.base_url}/datamap/api/search/query"
        params = {"api-version": "2023-09-01"}

        # Try with type filter first
        payload_with_filter = {
            "keywords": keyword,
            "limit": limit,
            "filter": {
                "or": [
                    {"entityType": "azure_sql_table"},
                    {"entityType": "hive_table"},
                    {"entityType": "DataSet"},
                    {"entityType": "spark_table"},
                    {"entityType": "fabric_lakehouse_table"},
                    {"entityType": "tabular_schema"},
                    {"entityType": "snowflake_table"},
                    {"entityType": "snowflake_view"}
                ]
            }
        }

        try:
            r = requests.post(url, headers=self._headers(), params=params,
                              json=payload_with_filter, timeout=30)

            results = []
            if r.status_code == 200:
                results = r.json().get("value", [])

            # Fall back to unfiltered search if no results
            if not results:
                payload_plain = {"keywords": keyword, "limit": limit}
                r2 = requests.post(url, headers=self._headers(), params=params,
                                   json=payload_plain, timeout=30)
                if r2.status_code == 200:
                    all_assets = r2.json().get("value", [])
                    # Post-filter: keep assets that look like tables (case-insensitive)
                    for asset in all_assets:
                        et = (asset.get("entityType") or "").lower()
                        at = " ".join(asset.get("assetType") or []).lower()
                        if "table" in et or "table" in at or "dataset" in et or "snowflake" in et:
                            results.append(asset)
                    # If still nothing, return everything so user can still pick
                    if not results:
                        results = all_assets

            tables = []
            for item in results:
                tables.append({
                    "id": item.get("id") or item.get("guid", ""),
                    "name": item.get("name", ""),
                    "qualifiedName": item.get("qualifiedName", ""),
                    "entityType": item.get("entityType", ""),
                    "assetType": ", ".join(item.get("assetType") or [])
                })
            return tables

        except requests.exceptions.RequestException as e:
            raise Exception(f"Table search failed: {str(e)}")

    # =========================================================
    # GET TABLE SCHEMA / COLUMNS
    # =========================================================
    def get_table_schema(self, guid, debug=False):
        """Fetch column definitions for a catalog table by its GUID"""
        entity_data = self.get_entity(guid, debug=debug)
        if not entity_data:
            return []

        columns = []
        entity = entity_data.get("entity", {})

        # Strategy 1: inline attributes.columns array
        inline_cols = entity.get("attributes", {}).get("columns", [])
        if isinstance(inline_cols, list) and inline_cols:
            for col in inline_cols:
                if isinstance(col, dict):
                    columns.append({
                        "name": col.get("displayText") or col.get("name", ""),
                        "dataType": col.get("typeName", col.get("dataType", "")),
                        "description": col.get("description", "")
                    })
            if columns:
                return columns

        # Strategy 2: relationshipAttributes.columns (GUID refs)
        rel_cols = entity.get("relationshipAttributes", {}).get("columns", [])
        if isinstance(rel_cols, list) and rel_cols:
            for col_ref in rel_cols:
                if isinstance(col_ref, dict):
                    name = col_ref.get("displayText") or col_ref.get("uniqueAttributes", {}).get("qualifiedName", "")
                    if name:
                        columns.append({
                            "name": name,
                            "dataType": col_ref.get("typeName", ""),
                            "description": ""
                        })
            if columns:
                return columns

        # Strategy 3: referredEntities in response
        referred = entity_data.get("referredEntities", {})
        for _, col_entity in referred.items():
            col_name = col_entity.get("attributes", {}).get("name", "")
            col_type = (col_entity.get("attributes", {}).get("dataType")
                        or col_entity.get("typeName", ""))
            if col_name:
                columns.append({
                    "name": col_name,
                    "dataType": col_type,
                    "description": col_entity.get("attributes", {}).get("description", "")
                })

        if columns:
            return columns

        # Strategy 4: Search catalog for child column entities via qualifiedName prefix
        try:
            qualified_name = entity.get("attributes", {}).get("qualifiedName", "")
            if qualified_name:
                search_url = f"{self.base_url}/datamap/api/search/query"
                params = {"api-version": "2023-09-01"}
                # Look for column entities whose qualifiedName starts with the table's qualifiedName
                payload = {
                    "keywords": "*",
                    "limit": 200,
                    "filter": {
                        "or": [
                            {"entityType": "column"},
                            {"entityType": "azure_sql_column"},
                            {"entityType": "hive_column"},
                            {"entityType": "spark_column"},
                            {"entityType": "snowflake_column"},
                            {"entityType": "fabric_lakehouse_column"},
                        ]
                    },
                    "facets": [],
                }
                r = requests.post(search_url, headers=self._headers(),
                                  params=params, json=payload, timeout=30)
                if r.status_code == 200:
                    for item in r.json().get("value", []):
                        item_qn = item.get("qualifiedName", "")
                        if item_qn.startswith(qualified_name):
                            col_name = item.get("name", "")
                            if col_name:
                                columns.append({
                                    "name": col_name,
                                    "dataType": item.get("entityType", ""),
                                    "description": ""
                                })
        except Exception:
            pass

        return columns

    # =========================================================
    # GET GOVERNANCE DOMAINS
    # =========================================================
    def get_governance_domains(self, debug=False):
        """Fetch governance domains from Purview Data Governance.
        Returns list of {id, name} dicts.
        """
        success, msg = self.authenticate(debug=debug)
        if not success:
            raise Exception(msg)

        api = "2025-09-15-preview"

        # ── Strategy 1: Direct domain-list endpoints ──────────────────────────
        domain_endpoints = [
            f"{self.base_url}/datagovernance/catalog/domains",
            f"{self.base_url}/datagovernance/catalog/governanceDomains",
            f"{self.base_url}/datagovernance/catalog/dataGovernanceDomains",
            f"{self.base_url}/datagovernance/catalog/catalogManagement/domains",
            f"{self.base_url}/datagovernance/governance-domains",
            f"{self.base_url}/datagovernance/domains",
        ]
        for url in domain_endpoints:
            for ver in [api, "2024-09-01-preview", "2023-09-01"]:
                try:
                    r = requests.get(url, headers=self._headers(),
                                     params={"api-version": ver}, timeout=15)
                    if debug:
                        print(f"GET {url} [{ver}] → {r.status_code}: {r.text[:200]}")
                    if r.status_code == 200:
                        data  = r.json()
                        items = (data.get("value") or data.get("items")
                                 or data.get("data") or (data if isinstance(data, list) else []))
                        result = [
                            {"id": d.get("id") or d.get("guid", ""),
                             "name": d.get("name") or d.get("displayName") or d.get("qualifiedName", "")}
                            for d in items if isinstance(d, dict)
                            and (d.get("id") or d.get("guid"))
                            and (d.get("name") or d.get("displayName"))
                        ]
                        if result:
                            return result
                except Exception:
                    continue

        # ── Strategy 2: Extract domains from CDEs (works when domain endpoints are 404) ──
        if debug:
            print("Direct domain endpoints all failed — extracting domains from CDEs...")
        try:
            r = requests.get(
                f"{self.base_url}/datagovernance/catalog/criticalDataElements",
                headers=self._headers(),
                params={"api-version": api, "$top": 1000},
                timeout=30
            )
            if r.status_code == 200:
                seen = {}   # id → name
                for item in r.json().get("value", []):
                    dom = item.get("domain")
                    if isinstance(dom, dict):
                        did   = dom.get("id", "")
                        dname = dom.get("name") or dom.get("displayName") or ""
                        if did and dname:
                            seen[did] = dname
                    elif isinstance(dom, str) and dom:
                        if dom not in seen:
                            seen[dom] = dom   # id == name if we only have a UUID
                if seen:
                    if debug:
                        print(f"Extracted {len(seen)} unique domains from CDEs")
                    return [{"id": k, "name": v} for k, v in seen.items()]
        except Exception as e:
            if debug:
                print(f"CDE-domain extraction failed: {e}")

        raise Exception(
            "Could not fetch governance domains — all direct endpoints returned 404 and "
            "no domain info was found in the CDEs. "
            "Make sure the service principal has the 'Governance Administrator' role AND "
            "that Data Governance is enabled on this Purview account."
        )
    def probe_governance_domains(self):
        """Diagnostic: hit every known domain endpoint and return a report.
        Returns list of dicts:
          { url, status, error, raw_preview, domains_found }
        Never raises — all exceptions are captured in the report.
        """
        success, msg = self.authenticate()
        if not success:
            return [{"url": "auth", "status": None, "error": msg,
                     "raw_preview": "", "domains_found": []}]

        api = "2025-09-15-preview"
        report = []

        candidate_urls = [
            (f"{self.base_url}/datagovernance/catalog/domains",             "GET"),
            (f"{self.base_url}/datagovernance/catalog/governanceDomains",   "GET"),
            (f"{self.base_url}/datagovernance/catalog/dataGovernanceDomains","GET"),
            (f"{self.base_url}/datagovernance/catalog/catalogManagement/domains","GET"),
            (f"{self.base_url}/datagovernance/governance-domains",           "GET"),
            (f"{self.base_url}/datagovernance/domains",                      "GET"),
        ]

        for url, method in candidate_urls:
            entry = {"url": url, "status": None, "error": None,
                     "raw_preview": "", "domains_found": []}
            try:
                if method == "GET":
                    r = requests.get(url, headers=self._headers(),
                                     params={"api-version": api}, timeout=15)
                else:
                    r = requests.post(url, headers=self._headers(),
                                      params={"api-version": api},
                                      json={"limit": 100}, timeout=15)

                entry["status"] = r.status_code
                entry["raw_preview"] = r.text[:600]

                if r.status_code == 200:
                    data  = r.json()
                    items = (data.get("value") or data.get("items")
                             or data.get("data") or (data if isinstance(data, list) else []))
                    for d in items:
                        if not isinstance(d, dict):
                            continue
                        did   = d.get("id") or d.get("guid", "")
                        dname = (d.get("name") or d.get("displayName")
                                 or d.get("qualifiedName") or "")
                        if did:
                            entry["domains_found"].append({"id": did, "name": dname})

            except Exception as e:
                entry["error"] = str(e)

            report.append(entry)

        return report

    # =========================================================
    # GET DATA PRODUCTS PER GOVERNANCE DOMAIN
    # =========================================================
    def get_domains_with_data_products(self, debug=False):
        """Return all governance domains that hold at least one data product.

        Returns list of:
          { id, name, data_products: [ {id, name, description, status} ] }
        """
        success, msg = self.authenticate(debug=debug)
        if not success:
            raise Exception(msg)

        api = "2025-09-15-preview"

        # ── Step 1: fetch all domains ─────────────────────────────────────
        domains = self.get_governance_domains(debug=debug)
        if not domains:
            return []

        # ── Step 2: for each domain, fetch its data products ─────────────
        result = []
        dp_endpoints = [
            # Most-likely paths for the DG preview API
            "/datagovernance/catalog/dataProducts",
            "/datagovernance/catalog/data-products",
        ]

        # Try fetching all data products once (filter client-side by domain)
        all_products = []
        for ep in dp_endpoints:
            try:
                r = requests.get(
                    f"{self.base_url}{ep}",
                    headers=self._headers(),
                    params={"api-version": api},
                    timeout=20
                )
                if r.status_code == 200:
                    all_products = r.json().get("value", [])
                    if debug:
                        print(f"Fetched {len(all_products)} data products from {ep}")
                    break
            except Exception:
                continue

        # Build domain-id → name map
        domain_map = {d["id"]: d["name"] for d in domains}

        # Group products by domain id
        domain_products: dict = {}
        for dp in all_products:
            dp_id   = dp.get("id", "")
            dp_name = dp.get("name", "Unnamed")
            dp_desc = dp.get("description", "")
            dp_status = dp.get("status", "")
            dom = dp.get("domain") or dp.get("governanceDomain") or {}
            if isinstance(dom, dict):
                did = dom.get("id", "")
            elif isinstance(dom, str):
                did = dom
            else:
                did = ""
            if did:
                domain_products.setdefault(did, []).append({
                    "id": dp_id, "name": dp_name,
                    "description": self._clean_html(dp_desc),
                    "status": dp_status
                })

        # If global fetch returned nothing, try per-domain endpoint
        if not domain_products:
            per_domain_endpoints = [
                "/datagovernance/catalog/dataProducts?domainId={did}",
                "/datagovernance/catalog/domains/{did}/dataProducts",
                "/datagovernance/catalog/governanceDomains/{did}/dataProducts",
            ]
            for d in domains:
                did = d["id"]
                for tpl in per_domain_endpoints:
                    ep = tpl.replace("{did}", did)
                    try:
                        r = requests.get(
                            f"{self.base_url}{ep}",
                            headers=self._headers(),
                            params={"api-version": api},
                            timeout=15
                        )
                        if r.status_code == 200:
                            items = r.json().get("value", [])
                            if items:
                                domain_products[did] = [
                                    {
                                        "id":          p.get("id", ""),
                                        "name":        p.get("name", "Unnamed"),
                                        "description": self._clean_html(p.get("description", "")),
                                        "status":      p.get("status", ""),
                                    }
                                    for p in items
                                ]
                                break
                    except Exception:
                        continue

        # Assemble final list — only domains that have products
        for d in domains:
            did = d["id"]
            products = domain_products.get(did, [])
            if products:
                result.append({
                    "id":            did,
                    "name":          d["name"],
                    "data_products": products
                })

        return result

    def get_domain_id_by_name(self, domain_name, debug=False):
        """Resolve a governance domain name to its ID.
        Tries: exact match → case-insensitive → partial/contains match.
        Returns (domain_id, available_names) tuple.
        domain_id is None if not found."""
        domains = self.get_governance_domains(debug=debug)
        needle = domain_name.strip().lower()
        available = [d.get('name', '') for d in domains]

        # 1. Exact case-insensitive match
        for d in domains:
            if d.get('name', '').strip().lower() == needle:
                return d['id'], available

        # 2. Partial match: needle contained in domain name or vice versa
        for d in domains:
            dname = d.get('name', '').strip().lower()
            if needle in dname or dname in needle:
                return d['id'], available

        # 3. Word-level overlap (e.g. user types "Healthcare", domain is "Data Governance - Healthcare")
        needle_words = set(needle.replace('-', ' ').split())
        for d in domains:
            dname = d.get('name', '').strip().lower()
            dwords = set(dname.replace('-', ' ').split())
            if needle_words & dwords:  # any common word
                return d['id'], available

        return None, available

    # =========================================================
    # CREATE GOVERNANCE DOMAIN
    # =========================================================
    def create_governance_domain(self, name, description="", debug=False):
        """Create a new governance domain in Purview Data Governance.
        Returns (True, domain_id) on success or (False, error_message).

        Tries multiple strategies:
          1. POST to collection endpoints (several API versions + payload variants)
          2. PUT with a pre-generated UUID
          3. PUT using name/kebab-case as resource key
        """
        import uuid as _uuid_mod
        import re as _re
        import urllib.parse as _up

        success, msg = self.authenticate(debug=debug)
        if not success:
            return False, f"Authentication failed: {msg}"

        base = self.base_url
        api_versions = ["2025-09-15-preview", "2024-09-01-preview"]

        # Derive a safe qualified name (kebab-case)
        qname = _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        desc_plain = description or ""

        # Track all responses for a useful diagnostic message
        attempts = []  # list of (method, url, api, status, snippet)

        def _record(method, url, api, status, snippet):
            attempts.append(f"  {method} {url} [{api}] → {status}: {snippet[:120]}")

        # ── Strategy 1: POST to collection endpoints ──────────────────────────
        collection_paths = [
            f"{base}/datagovernance/catalog/domains",
            f"{base}/datagovernance/catalog/governanceDomains",
        ]
        post_payloads = [
            {"name": name, "description": desc_plain},
            {"name": name, "qualifiedName": qname, "description": desc_plain},
            {"name": name, "qualifiedName": qname,
             "description": desc_plain, "status": "Active"},
        ]
        for path in collection_paths:
            for api in api_versions:
                for payload in post_payloads:
                    try:
                        r = requests.post(
                            path, headers=self._headers(),
                            params={"api-version": api},
                            json=payload, timeout=30
                        )
                        if debug:
                            print(f"[POST] {path} api={api} → {r.status_code}: {r.text[:300]}")
                        _record("POST", path, api, r.status_code, r.text)
                        if r.status_code in (200, 201):
                            data = r.json()
                            return True, data.get("id") or data.get("guid", "")
                        if r.status_code not in (400, 404, 405, 409, 422):
                            return False, f"HTTP {r.status_code}: {r.text[:400]}"
                    except requests.exceptions.RequestException as e:
                        _record("POST", path, api, "ERR", str(e))

        # ── Strategy 2: PUT with a pre-generated UUID ─────────────────────────
        new_id = str(_uuid_mod.uuid4())
        put_paths = [
            f"{base}/datagovernance/catalog/domains/{new_id}",
            f"{base}/datagovernance/catalog/governanceDomains/{new_id}",
        ]
        put_payloads = [
            {"id": new_id, "name": name, "description": desc_plain},
            {"id": new_id, "name": name, "qualifiedName": qname,
             "description": desc_plain, "status": "Active"},
        ]
        for path in put_paths:
            for api in api_versions:
                for payload in put_payloads:
                    try:
                        r = requests.put(
                            path, headers=self._headers(),
                            params={"api-version": api},
                            json=payload, timeout=30
                        )
                        if debug:
                            print(f"[PUT] {path} api={api} → {r.status_code}: {r.text[:300]}")
                        _record("PUT", path, api, r.status_code, r.text)
                        if r.status_code in (200, 201):
                            data = r.json()
                            return True, data.get("id") or data.get("guid") or new_id
                        if r.status_code not in (400, 404, 405, 409, 422):
                            return False, f"HTTP {r.status_code}: {r.text[:400]}"
                    except requests.exceptions.RequestException as e:
                        _record("PUT", path, api, "ERR", str(e))

        # ── Strategy 3: PUT using name as resource key ────────────────────────
        name_enc = _up.quote(name, safe="")
        for key in [name_enc, qname]:
            path = f"{base}/datagovernance/catalog/domains/{key}"
            for api in api_versions:
                try:
                    r = requests.put(
                        path, headers=self._headers(),
                        params={"api-version": api},
                        json={"name": name, "description": desc_plain}, timeout=30
                    )
                    if debug:
                        print(f"[PUT-name] {path} api={api} → {r.status_code}: {r.text[:300]}")
                    _record("PUT", path, api, r.status_code, r.text)
                    if r.status_code in (200, 201):
                        data = r.json()
                        return True, data.get("id") or data.get("guid") or name
                    if r.status_code not in (400, 404, 405, 409, 422):
                        return False, f"HTTP {r.status_code}: {r.text[:400]}"
                except requests.exceptions.RequestException as e:
                    _record("PUT", path, api, "ERR", str(e))

        # All strategies exhausted — build a helpful diagnostic message
        statuses = {str(a.split("→")[1].split(":")[0].strip()) for a in attempts if "→" in a}
        if statuses == {"404"} or "404" in statuses and len(statuses) <= 2:
            hint = (
                "All domain creation endpoints returned 404. "
                "This usually means the service principal lacks the "
                "'Governance Administrator' (or 'Data Governance Administrator') "
                "role in your Purview account, or the Unified Catalog / "
                "Data Governance feature is not enabled. "
                "Please assign the role in the Microsoft Purview governance portal "
                "under Settings → Role assignments."
            )
        else:
            hint = "All creation strategies failed. Responses:\n" + "\n".join(attempts[-6:])

        return False, hint

    # =========================================================
    # PUSH CDE TO PURVIEW DATA GOVERNANCE
    # =========================================================
    def get_cde_names_in_domain(self, domain_id, debug=False):
        """Fetch all existing CDE names in the specified domain.
        Returns a set of CDE names (lowercased) for fast duplicate checks.
        """
        success, msg = self.authenticate(debug=debug)
        if not success:
            return set()

        url = f"{self.base_url}/datagovernance/catalog/criticalDataElements"
        api_version = "2025-09-15-preview"
        existing_names = set()
        try:
            r = requests.get(url, headers=self._headers(),
                             params={"api-version": api_version, "$top": 1000}, timeout=20)
            if r.status_code == 200:
                for item in r.json().get("value", []):
                    dom = item.get("domain")
                    did = ""
                    if isinstance(dom, dict):
                        did = dom.get("id", "")
                    elif isinstance(dom, str):
                        did = dom
                    if did == domain_id:
                        item_name = item.get("name", "")
                        if item_name:
                            existing_names.add(item_name.strip().lower())
        except Exception:
            pass
        return existing_names

    def push_cde_to_purview(self, name, description, domain_id=None, data_type="String", debug=False):
        """Write a Critical Data Element to Purview Data Governance.
        POSTs to the same endpoint used by fetch_cdes().
        If domain_id is supplied, writes ONLY to that domain (no fallback).
        Returns (True, response_dict) on success or (False, error_message).
        Returns (True, {"status": "AlreadyExists"}) if the CDE name already exists in the domain.
        """
        success, msg = self.authenticate(debug=debug)
        if not success:
            return False, f"Authentication failed: {msg}"

        url = f"{self.base_url}/datagovernance/catalog/criticalDataElements"
        api_version = "2025-09-15-preview"

        # dataType must be one of: Text, Number, DateTime, Boolean
        _dtype_map = {
            "string": "Text", "str": "Text", "text": "Text",
            "varchar": "Text", "nvarchar": "Text", "char": "Text",
            "integer": "Number", "int": "Number", "bigint": "Number",
            "smallint": "Number", "decimal": "Number", "numeric": "Number",
            "number": "Number", "float": "Number", "double": "Number",
            "long": "Number",
            "boolean": "Boolean", "bool": "Boolean", "bit": "Boolean",
            "date": "DateTime", "datetime": "DateTime", "timestamp": "DateTime",
        }
        dt_str = _dtype_map.get(str(data_type).lower().strip(), "Text")

        existing_contacts = None

        if domain_id:
            # ── Caller provided a domain: use ONLY that domain, no fallback ──
            candidate_domain_ids = [domain_id.strip()]
            # Collect contacts from any existing CDE for the payload
            try:
                r = requests.get(url, headers=self._headers(),
                                 params={"api-version": api_version, "$top": 100}, timeout=15)
                if r.status_code == 200:
                    for item in r.json().get("value", []):
                        if existing_contacts is None:
                            existing_contacts = item.get("contacts")
                        break
            except Exception:
                pass
        else:
            # ── No domain provided: auto-detect from existing CDEs ──
            candidate_domain_ids = []
            try:
                r = requests.get(url, headers=self._headers(),
                                 params={"api-version": api_version, "$top": 100}, timeout=15)
                if r.status_code == 200:
                    items = r.json().get("value", [])
                    seen = {}
                    for item in items:
                        dom = item.get("domain")
                        did = ""
                        if isinstance(dom, dict):
                            did = dom.get("id", "")
                        elif isinstance(dom, str):
                            did = dom
                        if did and did not in seen:
                            seen[did] = True
                            candidate_domain_ids.append(did)
                        if existing_contacts is None:
                            existing_contacts = item.get("contacts")
            except Exception:
                pass

        contacts = existing_contacts if existing_contacts else {"experts": [], "owners": []}

        base_payload = {
            "name": name,
            "description": f"<p>{description}</p>" if description else "<p></p>",
            "dataType": dt_str,
            "status": 1,   # integer enum: 0=Draft, 1=Active, 2=Archived
            "contacts": contacts,
        }

        last_error = "No domains available to try."
        for did in candidate_domain_ids:
            payload = {**base_payload, "domain": did}
            if debug:
                print(f"POST {url} ?api-version={api_version} domain={did}")
                print(f"Payload: {payload}")
            try:
                r = requests.post(url, headers=self._headers(),
                                  params={"api-version": api_version},
                                  json=payload, timeout=30)
                if debug:
                    print(f"Response: {r.status_code} — {r.text[:400]}")
                if r.status_code in (200, 201):
                    resp = r.json()
                    resp.setdefault("_written_domain_id", did)
                    return True, resp
                if r.status_code == 409:
                    return True, {"name": name, "status": "AlreadyExists", "_written_domain_id": did}
                if r.status_code == 403:
                    last_error = f"HTTP 403 on domain {did}: {r.text[:300]}"
                    if domain_id:
                        # No fallback when domain was explicitly specified
                        return False, (
                            f"HTTP 403 Forbidden for domain {did}. "
                            "Service principal needs 'Data Curator' role in Purview → "
                            "Data Governance → Domains → [domain] → Settings → Role assignments.\n"
                            f"Error: {last_error}"
                        )
                    continue   # try next domain (auto-detect mode only)
                return False, f"HTTP {r.status_code}: {r.text[:400]}"
            except requests.exceptions.RequestException as e:
                return False, f"Request failed: {str(e)}"

        # All domains returned 403
        return False, (
            f"HTTP 403 Forbidden on all {len(candidate_domain_ids)} domain(s) tried. "
            "Service principal needs 'Data Curator' role in Purview → "
            "Data Governance → Domains → [domain] → Settings → Role assignments.\n"
            f"Last error: {last_error}"
        )