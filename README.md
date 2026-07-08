# Production Drone Inspection Platform Backend

A production-grade, highly-scalable serverless backend built with **AWS SAM (Serverless Application Model)**, **Python 3.11**, and **AWS Lambda**. Designed around a robust **DynamoDB Single-Table Design**, this platform handles multi-tenant drone inspection lifecycles, structured logging with correlation IDs, and advanced telemetry analytics.

---

## 📖 Table of Contents
1. [Architecture & Flow](#-architecture--flow)
2. [Folder Structure](#-folder-structure)
3. [DynamoDB Single-Table Modeling](#-dynamo-db-single-table-modeling)
4. [Clean Architecture Design](#-clean-architecture-design)
5. [API Documentation](#-api-documentation)
6. [Advanced Production Features](#-advanced-production-features)
7. [Production Grade Standouts](#-production-grade-standouts)
8. [Getting Started & Local Testing](#-getting-started--local-testing)
9. [Infrastructure Deployment](#-infrastructure-deployment)
10. [Tradeoffs & Architectural Decisions](#-tradeoffs--architectural-decisions)
11. [Future Enhancements](#-future-enhancements)

---

## 🏗️ Architecture & Flow

The system consists of an **API Gateway HTTP API** routing requests to modular **AWS Lambda** handlers. The Lambda layer coordinates logic via services and repositories, interacting with **DynamoDB** (single-table metadata) and **Amazon S3** (private binary image storage).

### System Architecture Diagram
```mermaid
graph TD
    User([HTTP Client / Client App]) -->|HTTPS Requests| APIGW[API Gateway HttpApi]
    
    subgraph Serverless Backend (AWS Lambda)
        APIGW -->|Route| Handlers[Handlers Layer]
        Handlers -->|Validate Inputs| Models[Pydantic Models]
        Handlers -->|Orchestrate Logic| Services[Service Layer]
        Services -->|Query / Persist| Repos[Repository Layer]
    end

    subgraph Storage & DB Tier
        Repos -->|boto3 DynamoDB resource| DynamoDB[(DynamoDB Single Table)]
        Repos -->|boto3 S3 client| S3[("S3 Private Bucket\n(Image Storage)")]
    end
    
    style User fill:#d4ebf2,stroke:#333,stroke-width:2px;
    style APIGW fill:#ffc966,stroke:#e68a00,stroke-width:2px;
    style Handlers fill:#f9e6ff,stroke:#cc33ff,stroke-width:2px;
    style Services fill:#e6ffe6,stroke:#00cc44,stroke-width:2px;
    style Repos fill:#e6f2ff,stroke:#3385ff,stroke-width:2px;
    style DynamoDB fill:#ffe6e6,stroke:#ff3333,stroke-width:2px;
    style S3 fill:#ffe6e6,stroke:#ff3333,stroke-width:2px;
```

---

## 📂 Folder Structure

The project strictly follows the separation of concerns:
```
drone-inspection-backend/
├── src/
│   ├── handlers/                  # Lambda entrypoints (input parsing + controller response)
│   ├── services/                  # Business orchestration and timeline transitions
│   ├── repository/                # Data persistence layers (boto3 client & resources)
│   ├── models/                    # Pydantic validation & Domain Models
│   └── utils/                     # Shared cross-cutting concerns (logging, errors decorator, response helpers)
├── infrastructure/
│   └── template.yaml              # AWS SAM application template
├── docs/                          # Architectural and data modeling assets
├── tests/                         # Pytest test cases using Moto mocks
├── scripts/                       # Database seed scripts for local workspace bootstrapping
├── requirements.txt               # App dependencies
├── ruff.toml                      # Linter configuration
└── Makefile                       # Developer utilities
```

---

## 🗄️ DynamoDB Single-Table Modeling

To achieve high read-write performance and avoid table scans, we store all entities in a single table named `DroneInspectionTable`. 

* **Primary Key (PK)**: Partition Key (String)
* **Sort Key (SK)**: Sort Key (String)
* **GSI1 (GSI1PK, GSI1SK)**: Secondary index to query inspections by drone.
* **InvertedIndex (SK, PK)**: Swapped index to look up records (like Inspection parent context) with only an entity-level sort key ID.

### Key Mapping Matrix

| Entity Type | PK | SK | GSI1PK | GSI1SK | TTL Property |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Warehouse** | `ORG#<org_id>#WAREHOUSE#<warehouse_id>` | `METADATA` | - | - | - |
| **Drone** | `ORG#<org_id>#WAREHOUSE#<warehouse_id>` | `DRONE#<drone_id>` | - | - | - |
| **Inspection** | `ORG#<org_id>#WAREHOUSE#<warehouse_id>` | `INSPECTION#<inspection_id>` | `DRONE#<drone_id>` | `INSPECTION#<inspection_id>` | - |
| **Version History** | `ORG#<org_id>#WAREHOUSE#<warehouse_id>` | `INSPECTION#<inspection_id>#VERSION#<num>` | - | - | - |
| **Image** | `INSPECTION#<inspection_id>` | `IMAGE#<image_id>` | - | - | `ttl` (Only while `PENDING`) |
| **Event** | `INSPECTION#<inspection_id>` | `EVENT#<timestamp>#<event_id>` | - | - | - |
| **Idempotency**| `IDEMPOTENCY#<key>` | `RESULT` | - | - | `ttl` (24 Hours Expiry) |

For comprehensive access patterns and implementation designs, refer to [docs/dynamodb.md](file:///Users/aadityamohansamadhiya/vecros/docs/dynamodb.md).

---

## 🔌 API Documentation

### Standard Response Format
Every endpoint returns a standardized response containing:
```json
{
  "success": true,
  "message": "Human readable action feedback",
  "data": { ... },
  "requestId": "correlation-uuid"
}
```

### Endpoints List

#### 1. Create Inspection (Idempotent & Multi-Tenant)
* **Method & Path**: `POST /v1/inspections`
* **Headers**: `Idempotency-Key: <unique-uuid>` (Optional, but recommended)
* **Request Body**:
  ```json
  {
    "organization_id": "ORG-VECROS-INC",
    "warehouse_id": "11111111-1111-1111-1111-111111111111",
    "drone_id": "33333333-3333-3333-3333-333333333333"
  }
  ```
* **Response (201 Created)**:
  ```json
  {
    "success": true,
    "message": "Inspection created successfully",
    "data": {
      "organization_id": "ORG-VECROS-INC",
      "inspection_id": "99999999-9999-9999-9999-999999999999",
      "warehouse_id": "11111111-1111-1111-1111-111111111111",
      "drone_id": "33333333-3333-3333-3333-333333333333",
      "status": "CREATED",
      "version": 1
    }
  }
  ```

#### 2. Get Inspection (Time-Travel Supported)
* **Method & Path**: `GET /v1/inspections/{id}`
* **Query Parameters**:
  - `version`: `int` (Optional: specify to fetch a specific historical snapshot version)
* **Response (200 OK)**: Returns the matching inspection record state.

#### 3. Request Upload URL (Adaptive Tiering)
* **Method & Path**: `POST /v1/inspections/{id}/upload-url`
* **Request Body**:
  ```json
  {
    "file_size": 8388608,
    "content_type": "image/png",
    "checksum": "sha256checksumstring"
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "success": true,
    "message": "S3 pre-signed upload URL generated successfully",
    "data": {
      "imageId": "77777777-7777-7777-7777-777777777777",
      "uploadUrl": "https://...",
      "s3Key": "tenants/ORG-VECROS-INC/warehouses/1111/inspections/9999/images/7777.png",
      "storageClass": "INTELLIGENT_TIERING",
      "expiresIn": 900
    }
  }
  ```

#### 4. Get Inspection Knowledge Graph
* **Method & Path**: `GET /v1/inspections/{id}/graph`
* **Response (200 OK)**: Returns unified entity relations, images, chronological event timeline, and live asset health scores.

#### 5. Get Inspection Replay Log
* **Method & Path**: `GET /v1/inspections/{id}/replay`
* **Response (200 OK)**: Returns the chronological event timeline with offset seconds from genesis, allowing frontends to replay audit timeline logs.

#### 6. Explain Query
* **Method & Path**: `GET /v1/inspections/{id}/explain`
* **Response (200 OK)**: Returns indices accessed, projected keys, read capacity units (RCU) estimated, and engine latency metrics.

#### 7. Get Warehouse Digital Twin
* **Method & Path**: `GET /v1/warehouses/{id}/digital-twin`
* **Response (200 OK)**: Returns real-time drone assets battery telemetry, total inspections ran, and active workload profiles.

#### 8. Get Warehouse Predictive Capacity Forecast
* **Method & Path**: `GET /v1/warehouses/{id}/predictive-capacity`
* **Response (200 OK)**: Forecasts S3 storage capacity requirements and cost constraints over a 30-day window.

---

## ⚡ Advanced Production Features

### 1. Multi-Tenant Partitioning
To guarantee data isolation across organization scopes, the database and object storage are segregated at the root tier:
- **DynamoDB Partition Key**: Pre-pended with `ORG#<organization_id>#`.
- **S3 Key Organization**: Nested inside folders: `/tenants/<organization_id>/warehouses/...`.

### 2. Time-Travel Versioning Snapshot Logs
Every update to an inspection record writes an immutable copy of its attributes with sort key `INSPECTION#<id>#VERSION#<version_num>`. Clients can fetch `/v1/inspections/{id}?version=X` to inspect states at any point in time.

### 3. S3 Adaptive Storage Classes
The pre-signed S3 URL generator selects S3 storage classes adaptively based on object size:
- **Small Files (<= 5MB)**: Standard storage.
- **Large Files (> 5MB)**: S3 Intelligent-Tiering storage class to optimize cost transitions automatically.

### 4. Immutable Cryptographic Hash Chain
Timeline/audit events for an inspection are chained using a SHA-256 hash. The hash for the current event is computed as:
  $$Hash = SHA256(event\_id \parallel inspection\_id \parallel event\_type \parallel timestamp \parallel payload\_json \parallel previous\_hash)$$
This guarantees tamper-evidence. Any modifications to intermediate log payloads break the hash chain integrity.

---

## 💎 Production Grade Standouts

- **Least-Privilege IAM Scopes**: AWS SAM resources use fine-grained `DynamoDBCrudPolicy` and `S3CrudPolicy` mapped strictly to their respective buckets and tables. No broad wildcard permissions.
- **Optimistic Locking**: Inspections protect write actions using an incremental `version` validation block, checking conflict states prior to updating statuses.
- **Zero Table Scans Policy**: All list, query, and join operations leverage DynamoDB Partition Keys or Global Secondary Indexes (`GSI1` and `InvertedIndex`), guaranteeing $O(1)$ search latency.

---

## 🚀 Getting Started & Local Testing

### Prerequisites
* Python 3.9+
* Docker (for DynamoDB/S3 local mock services if testing via local-api)
* AWS CLI and AWS SAM CLI

### Running Tests
We write mocks using Moto to simulate real AWS API behavior.
To run the automated tests locally:
```bash
python3 -m pytest tests/ --cov=src --cov-report=term-missing -vv
```

### Running the Demo Simulation
Execute the demo simulator script:
```bash
python3 scripts/demo.py
```
This runs the entire end-to-end multi-tenant lifecycle, asserting S3 adaptive urls, SHA-256 chaining, digital twins, time-travel, and forecasting metrics.

---

## 🛠️ Infrastructure Deployment

Deploy to AWS using SAM CLI:
```bash
make deploy
```
The SAM script will automatically create the complete serverless architecture, Gateway mappings, and security boundaries.

---

## 🔮 Future Enhancements
* **SQS Queue integration**: Hand off heavy AI image processing to background workers.
* **Cognito Authorization**: Add JWT verification filters inside API Gateway routes.
* **WebSocket Live Timeline updates**: Stream audit log events live to operators.
