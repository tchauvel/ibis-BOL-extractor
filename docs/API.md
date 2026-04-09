# IBIS BOL Extractor: API Specification

The Ibis API provides a single, high-fidelity endpoint for extracting structured data from logistics documents using a Gemini Vision-LLM.

## Endpoints

### `GET /health`

Health check.

#### Response
```json
{ "status": "ok", "version": "2.0.0" }
```

---

### `POST /extract-bol`

Accepts a `multipart/form-data` upload of a PDF or image and returns a validated JSON object.

Also available at `/api/extract-bol` (Vercel routing alias).

#### Request Parameters
| Name | Type | Description |
| :--- | :--- | :--- |
| `file` | `file` | The PDF, PNG, JPG, or WEBP file to extract from. |

#### Response Schema (`UnifiedBOL`)

| Field | Type | Description |
| :--- | :--- | :--- |
| `bol_number` | `string` | Primary Bill of Lading number |
| `pro_number` | `string \| null` | Carrier PRO number |
| `waybill_number` | `string \| null` | Waybill / Airway Bill / AWB number |
| `order_number` | `string \| null` | Order or purchase order number |
| `web_id` | `string \| null` | Web ID # |
| `master_bol_indicator` | `boolean` | True if document is a Master BOL |
| `origin_country_code` | `string \| null` | ISO 3166-1 alpha-2 code of the shipper's country (e.g. `"FR"`, `"US"`) |
| `logistics_dates` | `object \| null` | See [LogisticsDates](#logisticsdates) |
| `shipper` | `object` | See [Entity](#entity) |
| `consignee` | `object` | See [Entity](#entity) |
| `third_party_bill_to` | `object \| null` | See [Entity](#entity) |
| `carrier_name` | `string` | Freight carrier name |
| `scac_code` | `string \| null` | Standard Carrier Alpha Code |
| `vessel_name` | `string \| null` | Ocean vessel name |
| `voyage_number` | `string \| null` | Ocean voyage number |
| `container_number` | `string \| null` | Container number |
| `seal_number` | `string \| null` | Container seal number |
| `temperature_setpoint_fahrenheit` | `float \| null` | Cold chain temperature setpoint (°F) |
| `temperature_recorder_number` | `string \| null` | Temperature recorder / data logger ID |
| `line_items` | `array` | See [LineItem](#lineitem) |
| `other_references` | `array` | See [DocumentReference](#documentreference) — catch-all for Plan#, Customer Ref, etc. |
| `grand_total_weight_lbs` | `float` | Total shipment weight in lbs |
| `grand_total_handling_units` | `integer` | Total number of handling units |
| `shipper_signature_present` | `boolean` | True if a physical shipper signature/stamp is visible |
| `carrier_signature_present` | `boolean` | True if a physical carrier signature/stamp is visible |

#### LogisticsDates

All date fields are normalized to `YYYY-MM-DD` (ISO 8601). Time fields are preserved as extracted.

| Field | Type | Description |
| :--- | :--- | :--- |
| `document_date` | `string \| null` | Generic date printed at the top of the form |
| `dispatch_or_ship_date` | `string \| null` | Dispatch or ship date |
| `delivery_date` | `string \| null` | Delivery or estimated delivery date |
| `appointment_time` | `string \| null` | Appointment time |
| `arrival_time` | `string \| null` | Arrival time |
| `leaving_time` | `string \| null` | Leaving / departure time |

#### Entity

| Field | Type | Description |
| :--- | :--- | :--- |
| `name` | `string` | Full legal name |
| `address.address_line` | `string` | Street address |
| `address.city` | `string` | City |
| `address.state` | `string` | State / region / department code |
| `address.zip_code` | `string` | Postal code |
| `address.country_code` | `string \| null` | ISO 3166-1 alpha-2 country code |
| `address.phone` | `string \| null` | Phone number |

#### LineItem

| Field | Type | Description |
| :--- | :--- | :--- |
| `handling_unit_qty` | `integer` | Number of handling units (pallets, skids…) |
| `handling_unit_type` | `string` | e.g. `PLT`, `SKD` |
| `package_qty` | `integer` | Number of inner packages (cartons, boxes…) |
| `package_type` | `string` | e.g. `Cartons`, `Boxes` |
| `weight_lbs` | `float` | Line weight in lbs |
| `item_description` | `string` | Commodity description |
| `article_or_item_number` | `string \| null` | Article nr, Item code, UPC |
| `best_before_or_expiration_date` | `string \| null` | Best before / BDD / expiration date |
| `frozen_date` | `string \| null` | Frozen date (meat/seafood) |
| `batch_lot_number_or_supplier_ref` | `string \| null` | Batch/lot number or supplier reference |
| `nmfc_code` | `string \| null` | NMFC commodity code |
| `freight_class` | `float \| null` | Freight class |
| `is_hazardous` | `boolean` | True if line item is hazardous |
| `un_number` | `string \| null` | UN identification number (hazmat) |

#### DocumentReference

Catch-all for any reference numbers on the document that don't map to a primary schema field (e.g. Plan#, Customer Reference, Customer PO, Control#).

| Field | Type | Description |
| :--- | :--- | :--- |
| `reference_label` | `string` | Label as it appears on the document (e.g. `"Plan#"`, `"Customer Reference"`) |
| `reference_value` | `string` | The reference value |

#### Pipeline Metadata (`_pipeline`)
Each response includes a `_pipeline` object for telemetry:

| Field | Type | Description |
| :--- | :--- | :--- |
| `processing_time_ms` | `integer` | Total end-to-end latency in milliseconds |
| `pages_processed` | `integer` | Number of PDF pages rasterized |
| `model` | `string` | Gemini model used |
| `request_id` | `string` | UUID for tracing this request in server logs |

---

## Error Handling

| Code | Meaning |
| :--- | :--- |
| `400` | Bad Request — missing filename or unsupported file format |
| `413` | Payload Too Large — file exceeds the configured size limit |
| `429` | Too Many Requests — rate limit exceeded |
| `500` | Internal Server Error — LLM extraction or Pydantic validation failure |
