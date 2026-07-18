# Multi-AI-Agent-Service

Production-ready Multi-Agent AI Platform orchestrating intelligent agents using Groq LLM for real-time financial services. Process loan applications in <500ms with AI-powered eligibility assessment, and handle customer support via real-time order tracking and refund management.

**[👉 VISIT LIVE DEMO](https://d2wrk5t4qmgduv.cloudfront.net)** | **[📊 View Architecture](#-architecture)** | **[🚀 Deployment Guide](#-deployment)**

---

## ✨ Features

### 💰 Financial Agent
- **AI-Powered Loan Processing**: Groq LLM extracts and processes financial applications
- **Instant Eligibility Assessment**: Income validation (min AED 3,000), credit score checking (min 550)
- **Precision Calculations**: Decimal-based financial math for accurate interest rates
- **Professional Offers**: Auto-generated loan offers with unique IDs, valid 30 days
- **Interest Rate Tiers**:
  - Credit 750+: 3.5% APR
  - Credit 700-749: 4.5% APR
  - Credit 650-699: 5.5% APR
  - Credit <650: 7.0% APR
- **PDF Export**: Download professional loan offers
- **4-Step Wizard**: Personal Info → Financial Info → Loan Details → Review

### 🎧 Support Agent
- **Real-Time Order Lookup**: Query actual DynamoDB order data
- **Visual Status Tracking**: Order progression (Placed → Processing → Shipped → Delivered)
- **Refund Processing**: Automatic validation and approval
- **High-Value Monitoring**: Flag refunds >AED 10,000 for manual review
- **Complaint Management**: Priority-based ticket routing (24h urgent, 48h normal)
- **3-Step Process**: Your Details → Request → Review

### 📊 Platform Features
✅ **Dark Mode Toggle** - Professional UI preference
✅ **Real-Time Validation** - Form feedback as you type (green=valid, red=invalid)
✅ **Analytics Dashboard** - Track approvals, denials, response times
✅ **Activity Log** - Monitor all platform requests
✅ **Request History** - Last 5 interactions per agent
✅ **Chat Interface** - Natural conversational flow
✅ **Mobile Responsive** - Works on all devices

---

## 🏗️ Architecture
┌─────────────────────────────────────────────────────────────┐
│                    User Browser                               │
└────────────────────┬────────────────────────────────────────┘
│
↓
┌───────────────────────┐
│   CloudFront CDN      │  (Global Distribution)
│  (S3 + Cache)         │
└───────────┬───────────┘
│
↓
┌────────────────────────────────┐
│  API Gateway REST Endpoint     │
│  (CORS, Request Routing)       │
└───────────────┬────────────────┘
│
↓
┌────────────────────────────────┐
│   AWS Lambda Router            │  (Python 3.12)
│   (Single Function Handler)    │
└──┬─────────────────────────┬───┘
│                         │
↓                         ↓
┌─────────────┐         ┌──────────────┐
│  Financial  │         │   Support    │
│    Agent    │         │    Agent     │
└──────┬──────┘         └────────┬─────┘
│                         │
↓                         ↓
┌──────────────────────────────────────┐
│   Groq LLM Integration               │
│   - Prompt Engineering               │
│   - JSON Extraction                  │
│   - Retry Logic (3x, Exponential)   │
└──────────────┬───────────────────────┘
│
┌────────┴────────┐
↓                 ↓
┌─────────┐      ┌──────────┐
│ Extract  │      │ Validate │
│  Data    │      │  Rules   │
└─────────┘      └──────────┘
│                 │
└────────┬────────┘
↓
┌────────────────────────┐
│   AWS DynamoDB         │
│  - orders table        │
│  - refunds table       │
│  - tickets table       │
└────────────────────────┘
│
└─→ Mock Fallback (Graceful Degradation)
