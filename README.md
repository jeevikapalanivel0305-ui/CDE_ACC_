# CDE Catalyst: AI-Powered Critical Data Element Governance

![CDE Catalyst Dashboard](assets/preview.jpg)

CDE Catalyst is an advanced Data Governance platform developed by iLink Digital. It provides an intuitive, interactive interface for identifying, managing, and governing Critical Data Elements (CDEs) across multiple data systems. By integrating Google's Gemini AI and leading enterprise data platforms (Microsoft Purview and Microsoft Fabric), CDE Catalyst accelerates data governance workflows and automates risk assessment.

---

## 🚀 How It Works

CDE Catalyst operates on a comprehensive end-to-end data governance flow:

1. **Discovery & Ingestion**: Plugs directly into your existing enterprise data ecosystems. It extracts metadata and schemas from Microsoft Fabric (Lakehouses/Warehouses) or Microsoft Purview Data Catalogs. It also supports manual data ingestion via Excel or CSV uploads.
2. **AI-Powered Identification**: For datasets or schemas that lack explicit governance tagging, the Gemini-powered "AI Recommender" analyzes the dataset columns against a provided business context (e.g., "GDPR Compliance in Healthcare") and automatically flags potential CDEs.
3. **Qualification & Risk Assessment**: Business impact, regulatory compliance, data quality risk, security risk, and recovery difficulty are calculated to provide a unified "Weighted Risk Score". 
4. **Actionable Remediation**: Once risks are quantified, the platform utilizes generative AI to auto-generate actionable, prioritized mitigation plans tailored to each CDE's specific risk tier and domain.
5. **Dashboard & Tracking**: All CDEs, whether AI-discovered or manually onboarded, are persisted and visualized on a Central Dashboard, tracking their status and resolution progress.

---

## 🛠️ Technology Stack (What We Used)

The platform is designed to be lightweight, extensible, and powerful using modern Python frameworks:

* **Frontend**: [Streamlit](https://streamlit.io/) - Used to build the modern, interactive, and responsive web application UI. We implement custom CSS to achieve a polished, "accelerator-style" enterprise look.
* **Data Visualization**: [Plotly Express & Graph_Objects](https://plotly.com/python/) - Used for rendering interactive pie charts and bar charts for the centralized dashboard.
* **Data Processing**: [Pandas](https://pandas.pydata.org/) - Handles internal data states, data cleaning, and data frames (especially when uploading from Excel/CSV and formatting data for UI tables).
* **AI & Machine Learning**: `google-generativeai` (Gemini 2.5 Flash / 2.0 Flash) - Specifically drives the `ai_recommender.py` logic, enabling semantic analysis of table schemas and generating contextual risk mitigation actions.
* **Database & Connectivity**: 
    * `requests` - Handles REST API calls, primarily communicating with Microsoft Purview's Azure API endpoints.
    * `pyodbc` - Manages robust SQL connections to Microsoft Fabric SQL Endpoints allowing schema fetching and bulk data synchronization (`fast_executemany`).

---

## 🎯 Key Features

* **Interactive Dashboard**: A high-level overview visualization displaying total CDEs, risk tier distribution (Critical, High, Medium, Low), and domain-based breakdown.
* **Microsoft Purview Integration**: Direct connectivity to the Purview Data Map/Data Governance APIs to synchronize fully defined CDEs via Service Principal OAuth2 authentication.
* **Microsoft Fabric Integration**: Dynamic schema fetching from Fabric SQL endpoints (Lakehouses/Warehouses/KQL databases). Supports both interactive and Service Principal Azure AD authentication. Can also sync the updated CDE Register back into Fabric tables.
* **AI Recommender Engine**: Pass a table schema and a business requirement directly to the Gemini LLM. It responds with recommended CDE lists complete with business definitions and rationales.
* **Smart Action Suggestions**: Generate 2-3 specific, actionable recommendations and priority assignments (P1-P4) using Gemini based on a CDE's calculated risk profile.
* **Fully Persistent Session Management**: CDEs, form entries, connector credentials, and application states are persisted smoothly during user navigation.

---

## 📁 Project Structure

```bash
CDE_ACC/
│
├── cde.py                       # Main Streamlit Application (Frontend UI, Routing, Session State)
├── requirements.txt             # Python dependencies
├── style.css                    # Custom CSS variables and styling overrides
│
├── backend/                     # Backend Logic & Connectors
│   ├── __init__.py
│   ├── ai_recommender.py        # Gemini API orchestration (prompts & response parsing)
│   ├── fabric_connector.py      # Microsoft Fabric connectivity (AAD auth & pyodbc)
│   └── purview_connector.py     # Microsoft Purview connectivity (Azure REST APIs)
│
└── assets/                      # Static assets 
    └── ilink_logo.png           # Company branding
```

---

## ⚙️ Installation & Setup

### Prerequisites
* Python 3.8 or higher.
* Microsoft ODBC Driver 17 or 18 for SQL Server (Required for Fabric Connectivity).

### 1. Clone & Environment Setup
Clone the repository and create a virtual environment:
```bash
git clone <repository-url>
cd CDE_ACC
python -m venv venv
# On Windows
venv\Scripts\activate
# On macOS/Linux
source venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. API Keys and Secrets
Create a `.streamlit/secrets.toml` file in the root directory and add your Gemini API key:
```toml
# .streamlit/secrets.toml
GEMINI_API_KEY = "your_google_gemini_api_key_here"
```
*(Azure Client IDs, Tenant IDs, and Secrets for Purview and Fabric are entered interactively via the UI).*

### 4. Run the Application
Launch the Streamlit server:
```bash
streamlit run cde.py
```
The application will automatically open in your default web browser at `http://localhost:8501`.
