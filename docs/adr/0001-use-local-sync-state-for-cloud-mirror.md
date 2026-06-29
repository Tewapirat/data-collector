# Use local sync state for the cloud mirror

The OneDrive cloud mirror will track uploaded CSV files with local sync state keyed by each file's mirror path and content hash. This keeps local CSV files as the source of truth, makes retries idempotent, and avoids relying on OneDrive metadata to decide whether a generated file needs to be uploaded again.
