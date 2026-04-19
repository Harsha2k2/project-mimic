# LLD 24: Disaster Recovery Backup and Restore Automation

## Feature

Needed + Missed #17: Add disaster recovery backup and restore automation and validation.

## Scope

Add a scheduled backup/restore validation pipeline driven by a repository manifest of important persistent files.

- Define backup targets in a YAML manifest.
- Archive the configured files into a tarball.
- Restore the tarball into a temporary directory and compare hashes.
- Fail if any target is missing or does not round-trip correctly.

This increment provides validation automation and a concrete backup mechanism for file-backed state.

## Manifest

`config/disaster-recovery.yml` contains:

- `backup_targets`: list of file paths to archive.
- `archive_path`: output tarball path.

## Workflow Design

1. Load the manifest.
2. Build a backup archive from the configured targets.
3. Extract the archive to a temporary location.
4. Verify that each file round-trips byte-for-byte.
5. Exit non-zero if validation fails.

## Failure Policy

- Missing manifest or invalid YAML fails the job.
- Missing backup targets fail the job.
- Restore mismatch fails the job.

## Rollout

1. Start with the highest-value runtime persistence files.
2. Add any additional stateful artifacts as they are introduced.
3. Run the workflow on a schedule and before major releases.
