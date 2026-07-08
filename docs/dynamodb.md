# DynamoDB Single Table Design Documentation

This project uses a single-table DynamoDB design, where all domain entities are stored in one table. This reduces network round-trips, simplifies database management, and guarantees scalable, constant-time (O(1)) operations.

## Primary Table Key Schema

- **Partition Key (PK)**: `String`
- **Sort Key (SK)**: `String`

### Global Secondary Indexes (GSIs)

1. **GSI1**: Used to query collections by a non-primary key dimension.
   - **GSI1PK**: `String`
   - **GSI1SK**: `String`
2. **InvertedIndex**: Used as an inverted GSI to fetch parent/child entities by ID alone when the parent's identifier is missing from the request context.
   - **SK**: Partition Key
   - **PK**: Sort Key

---

## Entity-to-Key Mapping Table

| Entity Type | PK Pattern | SK Pattern | GSI1PK Pattern | GSI1SK Pattern | Description / Purpose |
|:---|:---|:---|:---|:---|:---|
| **Warehouse** | `WAREHOUSE#<warehouse_id>` | `METADATA` | - | - | Store warehouse profile details (e.g. name, location). |
| **Drone** | `WAREHOUSE#<warehouse_id>` | `DRONE#<drone_id>` | - | - | Store drone physical assets linked to their parent warehouse. |
| **Inspection** | `WAREHOUSE#<warehouse_id>` | `INSPECTION#<inspection_id>` | `DRONE#<drone_id>` | `INSPECTION#<inspection_id>` | Store inspection metadata, statuses, and concurrency version tags. |
| **Image** | `INSPECTION#<inspection_id>` | `IMAGE#<image_id>` | - | - | Track pre-signed image upload records, files details, and status. |
| **Event** | `INSPECTION#<inspection_id>` | `EVENT#<timestamp>#<event_id>` | - | - | Immutable audit log history records of changes to an inspection. |
| **Idempotency**| `IDEMPOTENCY#<key>` | `RESULT` | - | - | Store requests/responses cache to enforce API idempotency. |

---

## Access Pattern Implementation Details

### 1. Create Idempotent Inspection
- **Operation**: `PutItem` (or `UpdateItem` with conditions)
- **Primary Table Key**:
  - `PK = WAREHOUSE#<warehouse_id>`
  - `SK = INSPECTION#<inspection_id>`
- **Conditional Check**: The handler uses `IDEMPOTENCY#<key>` and `RESULT` in an atomic conditional lock to verify the request hasn't run already.

### 2. List Warehouse Inspections
- **Operation**: `Query`
- **Primary Table Key**:
  - `PK = WAREHOUSE#<warehouse_id>`
  - `SK` begins_with `INSPECTION#`
- **Efficiency**: Direct query, scan-free.

### 3. List Drone Inspections
- **Operation**: `Query` on `GSI1` index
- **Index Key**:
  - `GSI1PK = DRONE#<drone_id>`
  - `GSI1SK` begins_with `INSPECTION#`
- **Efficiency**: Direct index query, scan-free.

### 4. Generate Pre-signed URL & Register Image Upload
- **Operation**: `PutItem` for image metadata.
- **Primary Table Key**:
  - `PK = INSPECTION#<inspection_id>`
  - `SK = IMAGE#<image_id>`
- **TTL Support**: Stored with an attribute `ttl` (epoch integer timestamp set to 15 mins in future). If S3 upload fails or is abandoned, DynamoDB cleans it up automatically.

### 5. Confirm S3 Upload Complete
- **Operation**: `UpdateItem`
- **Primary Table Key**:
  - `PK = INSPECTION#<inspection_id>`
  - `SK = IMAGE#<image_id>`
- **Update Expression**: `SET status = UPLOADED REMOVE ttl`
- **Reason**: We clear the `ttl` attribute so that uploaded image metadata records are permanent and never deleted by the DynamoDB TTL sweeper.

### 6. Query Timeline / Audit Log
- **Operation**: `Query`
- **Primary Table Key**:
  - `PK = INSPECTION#<inspection_id>`
  - `SK` begins_with `EVENT#`
- **Sorting**: The sort key contains `EVENT#<timestamp>`. Since DynamoDB keeps elements sorted by sort key, queries naturally return events sorted chronologically.
