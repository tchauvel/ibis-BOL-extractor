# IBIS BOL Extractor: API Specification

The Ibis API provides a single, high-fidelity endpoint for extracting structured data from logistics documents using Gemini 3.1 Vision-LLM.

## Endpoints

### `POST /extract-bol`

Accepts a multiform/form-data upload of a PDF or image and returns a validated JSON object.

#### Request Parameters
| Name | Type | Description |
| :--- | :--- | :--- |
| `file` | `file` | The PDF, PNG, JPG, or WEBP file to extract from. |

#### Response Schema (`UnifiedBOL`)
The response is a strict JSON object containing the following keys (if found):

- **bol_number**: Primary Bill of Lading number.
- **carrier_name**: Identity of the freight carrier.
- **grand_total_weight_lbs**: Numeric weight in lbs.
- **line_items**: List of objects containing:
    - `handling_unit_qty`
    - `item_description`
    - `weight_lbs`
    - ... (see `api/lib/schema.py` for full details)

#### Metadata (`_pipeline`)
Each response contains a `_pipeline` object for telemetry:
- `processing_time_ms`: Total latency.
- `pages_processed`: Number of pages rasterized.
- `model`: The specific Gemini model used.

## Error Handling
- **400**: Bad Request (e.g., unsupported file format).
- **429**: Quota Exceeded (Gemini API limit reached).
- **500**: Internal Server Error (e.g., LLM extraction or Pydantic validation failure).
