# Tako AI
## The Glass-Box Identity Architect

---

## Hero Section

# Stop Trusting Black Boxes.
# Audit the Glass Box.

**Tako is the first Auditable AI for Okta.** It doesn't just guess—it explores, probes, and validates its logic step-by-step, right before your eyes.

**Thinks like an Engineer. Executes like a machine.**

[DEPLOY LOCALLY] [WATCH DEMO]

> *"Why can't user john.doe access Salesforce?"*
>
> **Tako:** *Checking user status (Active)... Checking group rules... Found 'Salesforce-Users'... User missing from group. Root cause identified.*

---

## The Core Difference

### ❌ The Problem: Black Box AI
Traditional LLM agents are opaque. They hallucinate, guess API endpoints, and hide their logic. You get an answer, but you can't trust how it got there.

### ✅ The Solution: Tako Glass Box
Tako operates on a strict **"Think → Log → Act"** protocol.
*   **100% Auditable:** Every API call, every logic branch, and every decision is logged in real-time.
*   **Safe Exploration:** It doesn't assume your schema; it probes it safely (`LIMIT 3`) to learn your environment.
*   **Self-Correcting:** If a query fails, Tako analyzes the error and adjusts its approach—just like a human engineer.

---

## How It Works: The Cognitive Loop

Tako replaces complex scripts with a transparent reasoning engine.

### 1. Perception & Discovery
You ask a natural language question. Tako scans your environment to understand which APIs are relevant, mapping relationships between Users, Groups, and Apps dynamically.

### 2. The "Rubber Duck" Reasoning
Before touching data, Tako formulates a plan. It explains its strategy in plain English (the "Thinking UI"), allowing you to verify its logic before execution.

### 3. Validated Execution
Tako generates Python code on the fly, runs it through a security sandbox (AST analysis, method whitelisting), and executes it. You see live progress bars, rate limits, and record counts.

---

## Use Cases

### 🔍 Root Cause Analysis
*"Why is the 'Engineering' group not syncing to Slack?"*
Tako traces the dependency chain across policies and assignments to find the break.

### 🛡️ Security Auditing
*"List all Super Admins who haven't signed in for 30 days."*
Instant visibility into dormant high-privilege accounts without writing SQL or Python.

### 📊 Compliance Reporting
*"Generate a CSV of all users and their assigned MFA factors."*
Turn complex API joins into simple downloadable reports.

---

## Enterprise Trust

**Your Data. Your Infrastructure. Your Rules.**

| Feature | Specification |
| :--- | :--- |
| **Deployment** | Local Docker Container (Self-Hosted) |
| **Data Privacy** | Zero data exfiltration. Logic runs locally. |
| **LLM Agnostic** | OpenAI, Anthropic, Azure, or **Local Ollama** (Air-gapped). |
| **Security** | OAuth 2.0 Private Key JWT. Read-Only modes available. |

---

## Get Started

**Ready to audit your AI?**

Clone the repo and start your first transparent investigation in minutes.

[GITHUB REPO] [READ THE DOCS]

---

## Footer

**Fctr Home** | Open-source Identity Tools
© 2025 Fctr. MIT License.

