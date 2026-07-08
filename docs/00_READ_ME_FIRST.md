# Executive Summary - Drone Inspection Platform Backend
**Submission Document: 00_READ_ME_FIRST.pdf**

---

## 👤 Candidate Details
* **Name**: Aaditya Mohan Samadhiya
* **Contact Number**: +91-9752853863
* **Email ID**: aaditya.samadhiya@adypu.edu.in
* **GitHub Repository**: [https://github.com/Aaditya29112005/vercos](https://github.com/Aaditya29112005/vercos)

---

## 🛠️ Technology Stack
* **Runtime**: Python 3.11
* **Infrastructure as Code (IaC)**: AWS SAM (Serverless Application Model) & CloudFormation
* **API Routing**: Amazon API Gateway (HTTP APIs)
* **Compute**: AWS Lambda
* **Database**: Amazon DynamoDB (Single-Table Design, GSI1, InvertedIndex)
* **Object Storage**: Amazon S3 (Adaptive storage tiering, secure pre-signed URLs)
* **Observability & Telemetry**: AWS Lambda Powertools, AWS X-Ray (Active Tracing), CloudWatch EMF (Embedded Metrics Format)
* **Testing Framework**: Pytest with Moto (AWS Mocking framework)

---

## 📝 Project Summary
A production-grade, highly-scalable serverless backend built to manage drone inspection lifecycles under a warehouse management system (WMS). The platform enforces rigid multi-tenant data isolation, adaptive S3 storage class management, and cryptographic tamper-evident event logging. Performance is optimized using a DynamoDB Single-Table layout designed for $O(1)$ search latency (Zero Table Scans), complete with structured correlation logging, active X-Ray tracing, and CloudWatch EMF custom operational metric logging.

---

## 🚀 Key Features Implemented

### Core Requirements
1. **Idempotent Inspection Creation**: `POST /v1/inspections` with validation and client-supplied `Idempotency-Key` headers.
2. **Scan-Free Warehouse Inspection Listing**: `GET /v1/warehouses/{id}/inspections` utilizing cursor-based pagination.
3. **High-Speed Drone Inspection Listing**: `GET /v1/drones/{id}/inspections` utilizing Global Secondary Index `GSI1`.
4. **Direct Pre-signed URL Uploads**: `POST /v1/inspections/{id}/upload-url` generating secure 15-minute S3 upload targets.
5. **List Images for Inspection**: `GET /v1/inspections/{id}/images` mapping image metadata from the database partition.

### Advanced SaaS Engineering (Bonus Features)
1. **Multi-Tenant Partition Isolation**: All DynamoDB entries are prefix-isolated using `ORG#<org_id>#` and S3 files are sorted inside `/tenants/<org_id>/` directories.
2. **S3 Adaptive Storage Class Tiering**: Automatically routes images $\le$ 5MB to `STANDARD` storage and images > 5MB to `INTELLIGENT_TIERING` to reduce storage costs.
3. **Time-Travel Versioning Snapshot Logs**: Status transitions copy historical versions under a snapshot sort key (`VERSION#X`), queryable via `GET /v1/inspections/{id}?version=X`.
4. **Knowledge Graph Joins**: `GET /v1/inspections/{id}/graph` compiles related warehouse metadata, drone telemetry, image states, and custom computed health metrics into a single request.
5. **Chronological Replay offsets**: `GET /v1/inspections/{id}/replay` formats event log offset timers in seconds from the genesis event.
6. **Immutable Cryptographic Hash Chaining**: Every timeline event logs a SHA-256 hash containing its predecessor's event hash, creating a tamper-evident audit record.
7. **explain Query Debug API**: `GET /v1/inspections/{id}/explain` outputs partition, key, index type, latency, and read capacity unit (RCU) estimates.
8. **Digital Twin Representation**: `GET /v1/warehouses/{id}/digital-twin` represents battery telemetry, workload details, and active operational states.
9. **Predictive Capacity Forecaster**: `GET /v1/warehouses/{id}/predictive-capacity` projects 30-day storage growth trends and risk boundaries.
10. **Centralized Cloud Observability**: Configured AWS X-Ray tracing, Powertools structured JSON context logging, and CloudWatch EMF custom indicators (`InspectionCreated`, `PresignedURLRequests`, `ImageUploads`, `UploadLatency`, and `Errors`).

---

## 📁 Google Drive Contents Map

```text
📁 Aaditya Mohan Samadhiya - VECROS SDE Backend Assessment/
│
├── 📄 00_READ_ME_FIRST.pdf           # This Executive Summary document
├── 📄 01_Project_Overview.pdf         # Detailed business/domain logic and feature lists
├── 📄 02_Architecture.pdf             # Architecture, sequence, and system data flows
├── 📄 03_DynamoDB_Design.pdf          # Single-Table schemas, index keys, and access query matrix
├── 📄 04_API_Documentation.pdf         # HTTP endpoint specifications and payload samples
├── 📄 05_Deployment_Guide.pdf          # Step-by-step local deployment instructions
├── 📄 06_Engineering_Decisions.pdf     # In-depth architectural trade-offs and rationale
├── 📄 07_Test_Report.pdf               # pytest output and test coverage report (81% coverage)
├── 📄 08_Performance_Notes.pdf         # Index lookup plans, CPU constraints, and storage optimizations
├── 📄 Resume.pdf                      # Candidate resume (PDF)
│
├── 📁 Demo/
│   ├── 🎥 Demo.mp4                    # 3-minute video walk-through demonstrating features
│   └── 📄 Demo-Script.pdf             # Script walk-through guide of the demonstration
│
├── 📁 Screenshots/                    # Console screen captures showing active AWS setups
│   ├── API Gateway.png
│   ├── Lambda Functions.png
│   ├── DynamoDB Table.png
│   ├── S3 Bucket.png
│   ├── IAM Roles.png
│   ├── CloudWatch Logs.png
│   ├── Postman Tests.png
│   └── Upload Flow.png
│
├── 📁 Postman/                        # Postman configuration files for reviewers
│   ├── Collection.json
│   └── Environment.json
│
├── 📁 Source Code/
│   └── aegis-inspect.zip             # Zip folder containing the source repository (excl. .git)
│
└── 📁 Diagrams/                       # Exported images of system architecture
    ├── Architecture.png
    ├── Sequence Diagram.png
    ├── ER Diagram.png
    ├── DynamoDB Access Patterns.png
    └── AWS Architecture.png
```

---

## 🎥 Demo Video Link
* **Google Drive Link**: `[Insert Google Drive Video Link Here after uploading Demo.mp4]`
