import streamlit as st
import json
import time
import pandas as pd
from openai import AzureOpenAI

_RETRY_STATUS_CODES = {503, 429, 500}
_MAX_RETRIES = 2
_RETRY_DELAYS = [3, 8, 20, 40]  # seconds between retries

def _call_openai_with_retry(client, model, prompt):
    """Call Azure OpenAI API with automatic retry on transient errors."""
    last_exc = None
    for retry, delay in enumerate(_RETRY_DELAYS[:_MAX_RETRIES]):
        if retry > 0:
            st.info(f"⏳ Rate limited. Waiting {delay}s before retry {retry}/{_MAX_RETRIES}…")
            time.sleep(delay)
        try:
            max_tokens = int(st.secrets.get("MAX_TOKENS", 4096))
            return client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=max_tokens
            )
        except Exception as e:
            err_str = str(e)
            is_retryable = any(str(code) in err_str for code in _RETRY_STATUS_CODES) or "rate_limit" in err_str.lower()
            if is_retryable:
                last_exc = e
                continue
            raise  # non-retryable — bubble up immediately
    raise last_exc

# Keep old name as alias so any external callers don't break
_call_gemini_with_retry = _call_openai_with_retry

def get_openai_client():
    """Initialize Azure OpenAI client from secrets"""
    try:
        endpoint   = st.secrets.get("AZURE_OPENAI_ENDPOINT")
        api_key    = st.secrets.get("AZURE_OPENAI_API_KEY")
        api_version = st.secrets.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
        if not endpoint or not api_key:
            st.error("⚠️ AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_API_KEY not found in secrets.")
            return None
        return AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version
        )
    except Exception as e:
        st.error(f"Error initializing Azure OpenAI client: {str(e)}")
        return None

# Aliases so existing code that calls get_gemini_client() / get_openai_client() still works
get_gemini_client = get_openai_client

# ============================================
# AI RECOMMENDATION LOGIC
# ============================================

def generate_cde_suggestions(business_requirement, industry="General", file_columns=None, file_sample=None):
    """Generate CDE suggestions using OpenAI based on business requirement, industry, and optional file schema"""
    client = get_openai_client()
    
    if not client:
        st.warning("⚠️ Azure OpenAI not configured. Please check AZURE_OPENAI_* keys in .streamlit/secrets.toml")
        return []
    
    # Construct Contextual Prompt
    context_part = f"Industry Context: {industry}\n"
    if file_columns:
        context_part += f"Table Columns ({len(file_columns)} total): {', '.join(file_columns)}\n"
        if file_sample is not None and not file_sample.empty:
            context_part += f"Sample Data (first {len(file_sample)} rows):\n{file_sample.to_string(index=False)}\n"
            task_instruction = """Task: Analyze the column names AND the actual sample data values above against the business requirement. Use the real data to understand what each column truly contains. Only recommend a column as a Critical Data Element (CDE) if it is directly indispensable to the business requirement — it is a key identifier, drives a regulatory obligation, determines financial outcome, or is a direct dependency for decision-making. Exclude audit timestamps, sequence numbers, and generic flags not tied to the business requirement."""
        else:
            task_instruction = """Task: Review each column strictly against the business requirement. Only recommend a column as a Critical Data Element (CDE) if removing it would make the business analysis impossible or significantly impaired — for example, it is the key identifier, drives a regulatory obligation, determines financial outcome, or is a direct dependency for decision-making. Do NOT recommend columns just because they exist. Columns like audit timestamps, sequence numbers, or generic flags that are not directly tied to the business requirement must be excluded."""
    else:
        task_instruction = """Task: Based on the business requirement, identify only the columns that are genuinely indispensable — without which the business analysis cannot be performed. Do not recommend columns merely because they are useful or present. Apply strict criteria: the column must be a key driver of the business outcome, a regulatory mandate, a risk determinant, or a core identifier."""

    prompt = f"""You are a strict data governance expert in the {industry} industry. Your role is to identify only the columns that are truly indispensable for the stated business requirement.
    {context_part}
    Business Requirement: "{business_requirement if business_requirement else 'Not specified — analyze based on the data and industry context.'}"
    {task_instruction}
    Domain must be one of: Retail, Healthcare, Finance, Manufacturing, Energy, Government, Insurance, Other.

    For each recommended CDE, provide a "criticality_reason" as one complete, meaningful sentence describing its direct business or governance significance — such as its role in regulatory compliance, financial impact, risk assessment, or core decision-making. Do NOT mention the column name inside the sentence. Do NOT use phrases like "without this" or "without which".

    Respond ONLY with a JSON array. Example:
    [
        {{
            "name": "column_name",
            "domain": "Domain Name",
            "definition": "Description...",
            "rationale": "Reasoning...",
            "criticality_reason": "Without this value, transaction risk cannot be assessed and regulatory reporting to the central bank would be non-compliant."
        }}
    ]
    """
    
    try:
        deployment = st.secrets.get("AZURE_OPENAI_DEPLOYMENTNAME", "gpt-4.1")
        response = _call_openai_with_retry(client, deployment, prompt)
        
        response_text = response.choices[0].message.content
        # Clean up code blocks if present
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
            
        result = json.loads(response_text)
        return result
    except Exception as e:
        st.error(f"❌ Error generating AI suggestions: {str(e)}")
        return []

def recommend_cdes_from_columns(table_name, columns, industry="General", table_metadata=None):
    """Recommend CDEs based on a table schema. If columns are empty, uses table metadata for inference."""
    client = get_openai_client()
    if not client: return []

    if columns:
        prompt = f"""You are a strict data governance expert in the {industry} industry. Your role is to identify only the columns that are truly indispensable for business analysis of table '{table_name}'.
    Columns ({len(columns)} total): {', '.join(columns)}

    For each column, ask: would the business analysis be impossible or critically impaired without this column? Only include it as a CDE if the answer is yes — for example, it is the core identifier, drives a regulatory requirement, determines financial outcome, or is a direct decision-making dependency.
    Exclude columns like audit timestamps, sequence/surrogate keys, generic flags, or any column not directly tied to business decision-making.

    For each recommended CDE provide:
    - name: exact column name
    - domain: one of Retail, Healthcare, Finance, Manufacturing, Energy, Government, Insurance, Other
    - definition: what this column represents
    - rationale: why it qualifies as a CDE
    - criticality_reason: one complete sentence describing its direct business or governance significance — such as its role in regulatory compliance, financial impact, risk assessment, or core decision-making. Do NOT mention the column name. Do NOT use phrases like "without this" or "without which".

    Respond ONLY with a JSON array."""
    else:
        # No columns available — infer CDEs from table name, qualified name, and entity type
        meta_info = ""
        if table_metadata:
            meta_info = (
                f"Qualified Name: {table_metadata.get('qualifiedName', 'N/A')}\n"
                f"Entity Type: {table_metadata.get('entityType', 'N/A')}\n"
                f"Asset Type: {table_metadata.get('assetType', 'N/A')}"
            )
        prompt = f"""You are a strict data governance expert in the {industry} industry.
    The following table exists in a data catalog but its column-level metadata is not yet populated:

    Table Name: {table_name}
    {meta_info}

    Based on the table name, qualified name, entity type, and industry context, infer the most likely columns this table would contain. Then identify which of those inferred columns would qualify as Critical Data Elements (CDEs) — columns that are core identifiers, drive regulatory requirements, determine financial outcomes, or are direct decision-making dependencies.

    For each recommended CDE provide:
    - name: the inferred column name
    - domain: one of Retail, Healthcare, Finance, Manufacturing, Energy, Government, Insurance, Other
    - definition: what this column likely represents in this table
    - rationale: why it qualifies as a CDE
    - criticality_reason: one complete sentence describing its direct business or governance significance. Do NOT mention the column name. Do NOT use phrases like "without this" or "without which".

    Respond ONLY with a JSON array."""

    try:
        deployment = st.secrets.get("AZURE_OPENAI_DEPLOYMENTNAME", "gpt-4.1")
        response = _call_openai_with_retry(client, deployment, prompt)
        text = response.choices[0].message.content
        if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text: text = text.split("```")[1].split("```")[0].strip()
        return json.loads(text)
    except Exception as e:
        st.error(f"❌ AI Error: {str(e)}")
        return []

class AIRecommender:
    def recommend_cdes_from_columns(self, table_name, columns, industry="General"):
        return recommend_cdes_from_columns(table_name, columns, industry)

def _resolve_fabric_creds(creds: dict) -> tuple:
    """Return (tenant_id, client_id, client_secret) for Fabric.
    Falls back to Purview credentials when Fabric-specific ones are not set,
    since both typically share the same Azure AD Service Principal."""
    tenant_id     = creds.get('fabric_tenant_id')     or creds.get('purview_tenant_id', '')
    client_id     = creds.get('fabric_client_id')     or creds.get('purview_client_id', '')
    client_secret = creds.get('fabric_client_secret') or creds.get('purview_client_secret', '')
    return tenant_id, client_id, client_secret

def render_ai_recommend():
    """Render AI CDE Recommendation Tab"""
    # Clean UI styling - no negative margins to avoid overlaps
    st.markdown("""
        <style>
        .ai-config-container {
            background-color: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            border: 1px solid #dee2e6;
            margin-top: 10px;
            margin-bottom: 20px;
        }
        /* Style adjustments for labels */
        .stSelectbox label, .stTextInput label {
            font-weight: 600 !important;
            margin-bottom: 4px !important;
        }
        </style>
    """, unsafe_allow_html=True)

    # Use HTML for header to avoid anchor links (the link icon)
    st.markdown('<h3 style="margin-bottom: 0px;">AI CDE Recommender</h3>', unsafe_allow_html=True)
    st.markdown('<div style="color: #666; margin-bottom: 20px;">Identify Critical Data Elements from your data source using AI analysis.</div>', unsafe_allow_html=True)
    
    if "ai_state" not in st.session_state:
        st.session_state.ai_state = {
            "industry": "General",
            "connector": "Excel",
            "f_sql": "",
            "f_db": "",
            "f_workspace_id": "",
            "f_item_id": "",
            "f_item_type": "Warehouse",
            "f_tab_sel": "--- Select Table ---",
            "f_tab_text": "",
            "requirement": ""
        }
    # Back-fill any keys missing from older session state
    _defaults = {"f_db": "", "f_workspace_id": "", "f_item_id": "", "f_item_type": "Warehouse"}
    for _k, _v in _defaults.items():
        if _k not in st.session_state.ai_state:
            st.session_state.ai_state[_k] = _v

    # Back-fill new keys for sessions created before this version
    for _k, _v in [("f_db", ""), ("f_workspace_id", ""), ("f_item_id", ""), ("f_item_type", "lakehouse")]:
        if _k not in st.session_state.ai_state:
            st.session_state.ai_state[_k] = _v

    def sync_ai_industry():
        st.session_state.ai_state["industry"] = st.session_state.ai_selected_industry
    def sync_ai_connector():
        st.session_state.ai_state["connector"] = st.session_state.ai_connector_type
    def sync_ai_f_sql():
        st.session_state.ai_state["f_sql"] = st.session_state.ai_f_sql_input
    def sync_ai_f_db():
        st.session_state.ai_state["f_db"] = st.session_state.ai_f_db_input
    def sync_ai_f_workspace_id():
        st.session_state.ai_state["f_workspace_id"] = st.session_state.ai_f_workspace_id_input
    def sync_ai_f_item_id():
        st.session_state.ai_state["f_item_id"] = st.session_state.ai_f_item_id_input
    def sync_ai_f_item_type():
        st.session_state.ai_state["f_item_type"] = st.session_state.ai_f_item_type_input
    def sync_ai_f_tab_sel():
        st.session_state.ai_state["f_tab_sel"] = st.session_state.ai_f_tab_sel_ref
    def sync_ai_f_tab_text():
        st.session_state.ai_state["f_tab_text"] = st.session_state.ai_f_tab_text_ref
    def sync_ai_requirement():
        st.session_state.ai_state["requirement"] = st.session_state.ai_requirement
    
    col_ind, col_conn = st.columns(2)
    
    with col_ind:
        st.markdown("**1. Industry Domain**")
        ind_options = ["General", "Finance / Banking", "Healthcare", "Retail / E-Commerce", "Manufacturing", "Energy / Utilities", "Insurance"]
        ind_idx = ind_options.index(st.session_state.ai_state["industry"]) if st.session_state.ai_state["industry"] in ind_options else 0
        selected_industry = st.selectbox("Industry", ind_options, index=ind_idx, key="ai_selected_industry", on_change=sync_ai_industry)
        
    with col_conn:
        st.markdown("**2. Data Source**")
        conn_options = ["Excel", "Microsoft Fabric"]
        conn_idx = conn_options.index(st.session_state.ai_state["connector"]) if st.session_state.ai_state["connector"] in conn_options else 0
        connector_type = st.selectbox("Connector", conn_options, index=conn_idx, key="ai_connector_type", on_change=sync_ai_connector)
        
        # Reset discovery when connector changes
        if 'prev_ai_connector' not in st.session_state or st.session_state.prev_ai_connector != connector_type:
            st.session_state.ai_discovered_cols = []
            st.session_state.prev_ai_connector = connector_type

    # Connector specific inputs
    file_columns = []
    fabric_table = None
    
    if connector_type == "Excel":
        uploaded_file = st.file_uploader("Upload Excel / CSV / JSON file", type=["csv", "xlsx", "xls", "json"])
        if uploaded_file:
            try:
                name = uploaded_file.name
                if name.endswith('.csv'):
                    df_preview = pd.read_csv(uploaded_file, nrows=10)
                elif name.endswith('.json'):
                    df_preview = pd.read_json(uploaded_file).head(10)
                else:
                    df_preview = pd.read_excel(uploaded_file, nrows=10)
                file_columns = df_preview.columns.tolist()
                st.session_state.ai_discovered_cols = file_columns
                st.session_state.ai_file_sample = df_preview
                st.session_state.ai_uploaded_filename = name
                st.success(f"✅ **{name}** — {len(file_columns)} columns, {len(df_preview)} sample rows loaded.")
                with st.expander("Preview uploaded data", expanded=False):
                    st.dataframe(df_preview, use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"Error reading file: {str(e)}")
        elif st.session_state.get('ai_discovered_cols') and st.session_state.get('ai_uploaded_filename'):
            # File was uploaded in a previous render — restore from session
            file_columns = st.session_state.ai_discovered_cols
            fname = st.session_state.ai_uploaded_filename
            st.info(f"📄 Using previously uploaded file: **{fname}** ({len(file_columns)} columns)")
    else:
        # Fabric Connector UI
        # ── Step 1: Item type ────────────────────────────────────────────
        f_item_type = st.radio(
            "Item Type",
            ["Warehouse", "Lakehouse"],
            index=0 if st.session_state.ai_state["f_item_type"] != "Lakehouse" else 1,
            horizontal=True,
            key="ai_f_item_type_input",
            on_change=sync_ai_f_item_type,
        )
        use_rest_api = True  # always use REST API; ODBC only as last resort

        # ── Step 2: Browse Workspaces ─────────────────────────────────────
        from backend.fabric_connector import FabricConnector as _FC
        creds = st.session_state.connector_creds
        t_id, c_id, c_sec = _resolve_fabric_creds(creds)

        if not all([t_id, c_id, c_sec]):
            st.warning("⚠️ Enter Tenant ID, Client ID, and Client Secret in the Purview tab first.")
        else:
            # Load workspaces once per session
            if 'ai_fabric_workspaces' not in st.session_state:
                st.session_state.ai_fabric_workspaces = []
            if not st.session_state.ai_fabric_workspaces:
                with st.spinner("Loading workspaces..."):
                    try:
                        _conn = _FC(t_id, c_id, c_sec)
                        st.session_state.ai_fabric_workspaces = _conn.list_workspaces()
                    except Exception as _e:
                        st.error(f"❌ Could not load workspaces: {_e}")

            workspaces = st.session_state.ai_fabric_workspaces
            if workspaces:
                ws_names = [w.get("displayName", w.get("id", "")) for w in workspaces]
                ws_ids   = [w.get("id", "") for w in workspaces]

                # Default to saved workspace if still valid
                saved_ws_id = st.session_state.ai_state["f_workspace_id"]
                default_ws_idx = ws_ids.index(saved_ws_id) if saved_ws_id in ws_ids else 0

                selected_ws_name = st.selectbox("Workspace", ws_names, index=default_ws_idx, key="ai_ws_sel")
                selected_ws_id   = ws_ids[ws_names.index(selected_ws_name)]
                st.session_state.ai_state["f_workspace_id"] = selected_ws_id

                # ── Step 3: Browse Items in selected workspace ────────────
                item_cache_key = f"ai_fabric_items_{selected_ws_id}_{f_item_type}"
                if item_cache_key not in st.session_state:
                    st.session_state[item_cache_key] = []
                if not st.session_state[item_cache_key]:
                    with st.spinner(f"Loading {f_item_type}s..."):
                        try:
                            _conn = _FC(t_id, c_id, c_sec)
                            st.session_state[item_cache_key] = _conn.list_items(selected_ws_id, f_item_type)
                        except Exception as _e:
                            st.error(f"❌ Could not load {f_item_type}s: {_e}")

                items = st.session_state[item_cache_key]
                if items:
                    item_names = [i.get("displayName", i.get("id", "")) for i in items]
                    item_ids   = [i.get("id", "") for i in items]

                    saved_item_id = st.session_state.ai_state["f_item_id"]
                    default_item_idx = item_ids.index(saved_item_id) if saved_item_id in item_ids else 0

                    selected_item_name = st.selectbox(f"{f_item_type}", item_names, index=default_item_idx, key="ai_item_sel")
                    selected_item_id   = item_ids[item_names.index(selected_item_name)]
                    st.session_state.ai_state["f_item_id"] = selected_item_id
                else:
                    st.info(f"No {f_item_type}s found in this workspace.")
                    selected_item_id = ""

        # Fetch Tables button
        fetch_col, _ = st.columns([1, 3])
        with fetch_col:
            fetch_clicked = st.button("🔍 Fetch Tables", key="ai_fetch_tables_btn")

        ws_id   = st.session_state.ai_state.get("f_workspace_id", "")
        item_id = st.session_state.ai_state.get("f_item_id", "")

        # Clear tables when selection changes
        conn_key = f"{ws_id}|{item_id}|{f_item_type}"
        if st.session_state.get('prev_f_sql') != conn_key:
            st.session_state.ai_fabric_tables = []
            st.session_state.prev_f_sql = conn_key

        if fetch_clicked:
            if not all([t_id, c_id, c_sec]):
                st.error("❌ Credentials missing. Enter them in the Purview tab.")
            elif not ws_id or not item_id:
                st.error("❌ Please select a workspace and item above.")
            else:
                with st.spinner(f"Fetching tables from {f_item_type}..."):
                    try:
                        connector = _FC(t_id, c_id, c_sec)
                        tables = connector.list_tables_via_api(ws_id, item_id, item_type=f_item_type.lower())
                        st.session_state.ai_fabric_tables = tables
                        if tables:
                            st.success(f"✅ Found {len(tables)} table(s).")
                            st.rerun()
                        else:
                            st.warning("No tables found. The item may be empty or the Service Principal needs Workspace Member access.")
                    except Exception as e:
                        st.warning(f"⚠️ {e}")
                        st.info("Enter the table name manually below.")

        # Fallback SQL endpoint (collapsed by default)
        with st.expander("Advanced: use SQL Analytics Endpoint instead", expanded=False):
            f_sql_val = st.session_state.ai_state["f_sql"] if st.session_state.ai_state["f_sql"] else st.session_state.connector_creds.get('fabric_sql_endpoint', '')
            f_sql = st.text_input("SQL Analytics Endpoint", value=f_sql_val, type="password",
                                  placeholder="xxxx.datawarehouse.fabric.microsoft.com",
                                  key="ai_f_sql_input", on_change=sync_ai_f_sql)
            f_db  = st.text_input("Database Name", value=st.session_state.ai_state["f_db"],
                                  placeholder="e.g. w1", key="ai_f_db_input", on_change=sync_ai_f_db)
            f_db_val = f_db.strip() if f_db and f_db.strip() else None
        f_sql = st.session_state.ai_state["f_sql"]   # keep in sync

        # Conditional Display: Dropdown vs Text Input
        fabric_tables = st.session_state.get('ai_fabric_tables', [])
        if fabric_tables:
            tab_options = ["--- Select Table ---"] + fabric_tables
            tab_idx = tab_options.index(st.session_state.ai_state["f_tab_sel"]) if st.session_state.ai_state["f_tab_sel"] in tab_options else 0
            fabric_table = st.selectbox("Select Table", tab_options, index=tab_idx, key="ai_f_tab_sel_ref", on_change=sync_ai_f_tab_sel)
            if fabric_table == "--- Select Table ---": fabric_table = None
        else:
            fabric_table = st.text_input("Table Name", placeholder="e.g. Sales_Transactions",
                                         value=st.session_state.ai_state["f_tab_text"],
                                         key="ai_f_tab_text_ref", on_change=sync_ai_f_tab_text)

        # Live column discovery (ODBC only, graceful skip for REST-only)
        if fabric_table and st.session_state.get('prev_ai_f_tab') != fabric_table:
            if f_sql and f_db_val:
                with st.spinner(f"Discovering attributes for '{fabric_table}'..."):
                    try:
                        connector = _FC(t_id, c_id, c_sec)
                        schema = connector.fetch_table_schema(f_sql, fabric_table, database_name=f_db_val)
                        if schema:
                            st.session_state.ai_discovered_cols = [c['name'] for c in schema]
                            st.session_state.prev_ai_f_tab = fabric_table
                        else:
                            st.session_state.ai_discovered_cols = []
                    except Exception as _e:
                        st.session_state.ai_discovered_cols = []
                        st.session_state.prev_ai_f_tab = fabric_table
            else:
                # No SQL endpoint — AI will infer from table name
                st.session_state.ai_discovered_cols = []
                st.session_state.prev_ai_f_tab = fabric_table

    # Business Requirement Input (optional when file is uploaded)
    req_placeholder = "Optional when a file is uploaded. Add business context for more targeted results, e.g. 'GDPR compliance for European customers'."
    requirement = st.text_area("Business Requirement / Context", 
                              height=100, 
                              placeholder=req_placeholder,
                              value=st.session_state.ai_state["requirement"],
                              key="ai_requirement", 
                              on_change=sync_ai_requirement)
    
    if st.button("Analyze & Recommend CDEs", type="primary"):
        # For Excel: restore columns from session if file was lost on rerender
        if connector_type == "Excel":
            cols_to_analyze = file_columns or st.session_state.get('ai_discovered_cols', [])
        else:
            cols_to_analyze = file_columns
        
        # Handle Fabric Fetching if needed
        if connector_type == "Microsoft Fabric":
            if not fabric_table:
                st.error("Please select or enter a table name.")
                return

            # Use already-discovered columns if available
            if st.session_state.get('prev_ai_f_tab') == fabric_table and st.session_state.get('ai_discovered_cols'):
                cols_to_analyze = st.session_state.ai_discovered_cols
            elif f_sql and f_db_val:
                # Try ODBC column discovery if SQL endpoint was entered in advanced section
                with st.spinner("Fetching table schema from Fabric..."):
                    try:
                        connector = _FC(t_id, c_id, c_sec)
                        schema = connector.fetch_table_schema(f_sql, fabric_table, database_name=f_db_val)
                        cols_to_analyze = [c['name'] for c in schema] if schema else []
                        if cols_to_analyze:
                            st.session_state.ai_discovered_cols = cols_to_analyze
                        else:
                            st.warning("Schema not available — AI will infer CDEs from the table name.")
                    except Exception as e:
                        st.warning(f"Could not fetch schema — AI will infer CDEs from the table name.")
                        cols_to_analyze = []
            else:
                # No schema available; AI infers CDEs from table name alone
                cols_to_analyze = []
        
        if not cols_to_analyze and not requirement:
            st.warning("Please upload a file or enter a business requirement to analyze.")
        elif connector_type == "Excel" and not cols_to_analyze:
            st.warning("Please upload a file first — no columns found to analyze.")
        else:
            # Main Analysis Logic
            with st.spinner("Analyzing file and identifying critical data elements..."):
                file_sample = st.session_state.get('ai_file_sample') if connector_type == "Excel" else None
                suggestions = generate_cde_suggestions(requirement, selected_industry, cols_to_analyze, file_sample=file_sample)
                st.session_state.ai_cde_suggestions = suggestions
                st.session_state.ai_discovered_cols = cols_to_analyze
                if suggestions:
                    st.success(f"Analysis complete. Identified {len(suggestions)} critical data element(s).")
                else:
                    st.warning("No critical CDEs identified based on the provided context.")
                
    # --- Live Attribute Display (Moved below Analyze button) ---
    if 'ai_discovered_cols' in st.session_state and st.session_state.ai_discovered_cols:
        st.markdown(f"**Discovered Attributes ({len(st.session_state.ai_discovered_cols)} found):**")
        cols_html = "".join([f"<span style='background:#f1f5f9; color:#475569; padding:2px 10px; border-radius:12px; margin-right:5px; margin-bottom:5px; display:inline-block; font-size:12px; border:1px solid #e2e8f0;'>{col}</span>" for col in st.session_state.ai_discovered_cols])
        st.markdown(f"<div>{cols_html}</div><div style='margin-bottom:15px;'></div>", unsafe_allow_html=True)
                
    # Display Results
    if 'ai_cde_suggestions' in st.session_state and st.session_state.ai_cde_suggestions:
        st.divider()
        
        st.subheader(f"Critical Data Elements ({len(st.session_state.ai_cde_suggestions)} identified)")

        # Get existing CDE names for checking status
        existing_names = [cde['name'].lower() for cde in st.session_state.cdes]
        
        for i, item in enumerate(st.session_state.ai_cde_suggestions):
            with st.container():
                api_col1, api_col2 = st.columns([4, 1])
                with api_col1:
                    st.markdown(f"**{item.get('name', 'N/A')}** <span style='background:#f3f4f6; padding:2px 8px; border-radius:10px; font-size:12px;'>{item.get('domain', 'Reference')}</span>", unsafe_allow_html=True)
                    st.markdown(f"_{item.get('definition', 'No definition provided')}_")
                    if item.get('criticality_reason'):
                        st.markdown(f"**Why Critical:** {item.get('criticality_reason')}")
                    else:
                        st.markdown(f"**Why Critical:** {item.get('rationale', item.get('reasoning', 'Not provided'))}")
                with api_col2:
                    # Check if already in registry
                    item_name = item.get('name', 'N/A')
                    if item_name.lower() in existing_names:
                        st.button("✅ Added", key=f"added_btn_{i}", disabled=True)
                    else:
                        if st.button("Add to Register", key=f"add_ai_cde_{i}", type="primary"):
                            # Dynamic Source Identification
                            source_system = "AI Recommended"
                            if connector_type == "Excel":
                                source_system = "Excel Source"
                            elif connector_type == "Microsoft Fabric":
                                source_system = "Microsoft Fabric"

                            # Add to CDE list
                            new_cde = {
                                "id": f"CDE-{len(st.session_state.cdes) + 100}", # Simple ID gen
                                "name": item.get('name', 'N/A'),
                                "domain": item.get('domain', 'Reference'),
                                "definition": item.get('definition', 'No definition provided'),
                                "sourceSystem": source_system,
                                "ai_suggested": True, # Flag as AI
                                "status": "Qualified", # Auto-qualified by AI
                                "businessImpact": 3, # Default
                                "regulatoryCompliance": 3,
                                "dataQualityRisk": 3,
                                "securityRisk": 3,
                                "systemComplexity": 3,
                                "recoveryDifficulty": 3,
                                "notes": f"Recommended by Gemini AI from {source_system}. Context: {requirement[:50]}..."
                            }
                            st.session_state.cdes.append(new_cde)
                            time.sleep(0.5)
                            st.rerun()
                st.divider()
