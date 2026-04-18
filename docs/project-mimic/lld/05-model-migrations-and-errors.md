# LLD: Model Migrations and Error Code Rules

## Schema Versioning

All public payload models include `schema_version`.

- Current version: `1.0`
- Rule: additive fields are allowed within major version.
- Rule: breaking changes require a new major schema version and migration note.

## Strict Validation Rules

- Unknown fields are rejected (`extra=forbid`).
- Assignment validation is enabled.
- Payload constraints raise deterministic validation failures.

## Error Code Mapping Rules

- `VALIDATION_ERROR`
  - Raised when Pydantic schema validation fails.
- `PAYLOAD_CONSTRAINT_VIOLATION`
  - Raised when domain constraint checks fail.
- `SERIALIZATION_ERROR`
  - Raised when serialization or unknown runtime conversion errors occur.

## Migration Notes

### Migration 1.0

1. Added `schema_version` to core and API payload models.
2. Enabled strict payload parsing with forbidden extra keys.
3. Added explicit machine error-code mapping helpers.

Backward compatibility:

- Existing payloads remain valid because `schema_version` defaults to `1.0`.
- Clients sending unknown keys must remove unsupported fields.
