# Antigen incident — P01 (example forensic report)

This is what Antigen files into the `Antigen/Incidents` KB folder via `save_document` for every hit. It holds only irreversible hashes — never the recoverable payload.

The `raw payload location` line below points at a checked-in file because P01 is one of the 12 corpus payloads. For an out-of-corpus hit on a real catalog there is no such file, and that line instead says so and points recovery at DataHub aspect version history — Antigen does not retain the removed text anywhere.

- entity: `urn:li:dataset:(urn:li:dataPlatform:snowflake,ecommerce.public.customers,PROD)`
- locus: entity-description
- surfaced by: `get_entities`
- detection signals: instruction-override
- categories: instruction-override
- content-sha256 (cleaned field): `7ecfe6e8ec055129883c4b7cf420753837565197fd80c8c67243ceadd0d564dc`
- payload-sha256 (removed payload, irreversible): `dfb313777035359b01a827838c53fcd629cc14389b7443d7b6a4019a415eb80c`
- raw payload location: repo `examples/payloads/P01.txt` (NEVER stored on the graph)

The injected span was **removed** from every agent-readable surface. This record cannot be obeyed or decoded back into the payload.
