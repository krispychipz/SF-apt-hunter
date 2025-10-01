# SF Apartment Hunter

## Overview
SF Apartment Hunter is a pipeline for discovering San Francisco apartment listings, extracting structured attributes from heterogeneous HTML pages, and emitting machine-readable summaries that downstream components can filter and forward as alerts.

Although the repository currently focuses on robust HTML parsing, the broader workflow is intended to consume a curated list of listing URLs (for example, from a `sites.yaml` inventory), apply user-defined screening rules (bedrooms, bathrooms, neighborhoods, price bands), and notify subscribers via email when fresh inventory appears.

## End-to-end pipeline

1. **Configuration ingestion** – Load `sites.yaml`, which enumerates source URLs and any per-site overrides (e.g., HTTP headers, throttling, or site-specific filter defaults). A lightweight orchestration script can iterate this collection, fetch the latest markup, and hand it to the extractor.
2. **Acquisition & parsing** – Each HTML payload is decoded and parsed with BeautifulSoup (or a bundled fallback) before being scanned for listing containers that mention prices and bedroom/bath tokens.
3. **Normalization & filtering** – Containers are converted into `Unit` objects by harvesting address, bedroom, bathroom, rent, and neighborhood attributes through reusable heuristics. Deduplication is enforced on the `(address, bedrooms, bathrooms, rent)` identity tuple so downstream filtering sees only unique units.
4. **Alert dispatch** – A post-processing layer evaluates business rules (neighborhood, bedroom count, price ceilings) against the parsed units and assembles email digests summarizing matching listings. Integrating with an SMTP relay or transactional email API completes the notification loop.

## Core modules

### `parser.cli`
Provides the command-line entry point (`parser-cli`) that decodes an HTML file, invokes the extractor, and writes JSON records. Flags control the input HTML path, canonical source URL, pretty-printing, and debug logging.

### `parser.extract`
Implements the DOM-walking extractor. It:
- Parses HTML into a soup, finds candidate containers that mention rent and bed/bath terms, and chooses the deepest unique containers to avoid nested duplicates.
- Builds `Unit` records by locating addresses, parsing bedroom/bathroom counts, normalizing rents, and cleaning neighborhood labels before returning structured results tied to their originating URL.
- Uses deterministic text iteration and attribute tokenization helpers to make heuristics resilient to inconsistent markup.

### `parser.heuristics`
Supplies reusable text parsers:
- `money_to_int` converts price phrases and ranges into integer rents, guarding against “call for pricing” noise.
- `parse_bedrooms`/`parse_bathrooms` interpret numeric and textual bedroom/bath variants (e.g., “Studio”, "3bd/2ba").
- `looks_like_address` and `clean_neighborhood` normalize location descriptors for consistent matching downstream.

### `parser.models`
Defines the `Unit` dataclass, encapsulating the structured listing attributes, a deduplication identity key, and JSON-friendly serialization for CLI output or alert payloads.

## Extending the pipeline

- **Configuration schema** – Expand `sites.yaml` to include per-source fetch intervals, authentication, and filter overrides. A controller script can maintain fetch state and pass site-specific metadata into `extract_units`.
- **Filtering hooks** – Implement predicates that accept `Unit` instances and evaluate neighborhood, bedroom, bathroom, and rent thresholds before queuing alerts.
- **Email delivery** – Assemble matching units into HTML or plaintext templates and send them via SMTP or services like SendGrid or AWS SES. Consider deduplicating alerts by unit identity to prevent repeated notifications for unchanged listings.

## Usage example

```bash
parser-cli --html downloads/mission.html --url https://example.com/listing-page --pretty
```

This command parses the saved HTML file, extracts unique listings, and prints a prettified JSON array—ready for downstream filtering and alerting logic.

## Testing
⚠️ Tests not run (not requested).
