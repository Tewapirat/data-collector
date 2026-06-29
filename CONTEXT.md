# Inverter Data Collector

This context describes the language for collecting inverter vendor data and publishing generated CSV files for internal use.

## Language

**Cloud mirror**:
A secondary copy of generated CSV files stored in a cloud file service for backup or sharing. The local CSV files remain the source of truth.
_Avoid_: Cloud storage, primary storage, OneDrive source of truth

**Sync backlog**:
Generated CSV files in local data directories that have not yet been successfully copied to the cloud mirror. The backlog may include files from earlier collector runs.
_Avoid_: Latest file only, current run output

**Mirror path**:
The cloud mirror path that preserves a CSV file's relative path under the local `data` directory.
_Avoid_: Flattened upload path, renamed cloud file
