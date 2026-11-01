# API key authentication

Machine clients can send a personal LandPPT key using `Authorization: Bearer KEY`
or `X-API-Key: KEY`. A key inherits its account's permissions and credits; it has
no separate read/write scopes. Verify the identity through `GET /api/auth/me`.

## Credential selection

An explicit Bearer header takes precedence over `X-API-Key`, and explicit keys
take precedence over session cookies. Invalid or empty keys are rejected without
falling back to cookie authentication, regardless of session cache state. Public
pages remain public and render anonymously when optional authentication fails.
Protected form routes also return JSON 401 when an explicit key is invalid.

Configured environment keys and personal keys must identify one credential.
Multiple environment users, duplicate stored keys, or overlapping personal and
environment bindings are rejected instead of selecting the first account. Logs
report ambiguity without recording the key.

## Database upgrade

Run the normal migration job through version `022` before starting the updated
application, including deployments with startup migrations disabled. The
migration adds a nullable `key_fingerprint` and a unique index, supports SQLite
and PostgreSQL, and is safe to apply repeatedly. New databases receive the same
constraint from SQLAlchemy metadata. No DDL runs inside authentication requests.

The deterministic SHA-256 fingerprint enforces uniqueness at the database level;
authentication continues to verify the per-key salted hash. Neither value is
returned by key-management APIs. Generate random keys rather than passwords or
predictable custom values.

Existing salted hashes cannot be backfilled without plaintext. Unique old keys
remain usable and receive a fingerprint after successful authentication; they
need not all be rotated. Creation checks old hashes using their own salts, and
the unique index catches concurrent new-key writes. A conflict rolls back the
write and returns the normal key-in-use error, preserving the prior key.

Historical duplicate values are deliberately rejected. Sign in using a browser
session and rotate conflicting personal keys, or remove conflicting environment
bindings. Automatic rotation is not performed because clients need the new
plaintext credential. Deleting a key or replacing its value releases its old
fingerprint. Automatic rollback of migration `022` is disabled so a migration
rollback cannot silently remove the uniqueness constraint; old application code
can tolerate the added nullable column but does not provide the new protections.

## API discovery

The authenticated OpenAPI document declares `BearerAuth`, `ApiKeyAuth` and
`SessionCookie` as alternatives on protected operations. Public operations have
an empty security requirement. API tools must still be given the selected
credential; importing a schema does not supply a secret.

Schema generation assigns unique operation IDs, including handlers registered
for multiple HTTP methods. If the same method/path is registered more than once,
the first runtime handler is documented; runtime routing is not changed. The
schema is cached normally. This does not add missing product features such as a
server-side equivalent of the editor's native SVG PPTX exporter.
