# Changelog

Changes in this fork since Cisco Catalyst Center MCP `release/3.2.3`.

## Unreleased

### Added

- Added the `api_readIssues` tool for paginated Assurance issue retrieval.
  It accepts page sizes from 1 to 25 and uses one-based offsets.
- Added the optional `CATALYST_CENTER_DEVICE_HEALTH_MAX_AGE_DAYS` setting.
  When configured, the Device Health tool advertises the limit and rejects
  older `endTime` values before calling the controller.

### Fixed

- Preserved integer query values without a decimal suffix and kept fractional
  values for arguments that allow them. Device Health timestamps use integer
  UTC epoch milliseconds.
- Exposed generated enum constraints in MCP tool schemas and rejected invalid
  enum values, non-integer input for integer fields, and reversed query time
  windows before calling the controller.
- Reported controller API failures as MCP tool errors, keeping successful
  empty results distinct.

### Documentation and tests

- Documented the purpose and development direction of this fork in the README.
- Added regression tests for request serialization, input validation, error
  propagation, and pagination using synthetic controller responses.

## Upstream changelog policy

A changelog will not be provided with each release.  The functionality of the MCP server is 
tightly coupled to the public api footprint.  Please reference the changelog for the public 
api found on DevNet for specific capability changes.  However, since the Api contracts are 
expected to be backward compatible, there should be minimal impact on MCP server capabilities.
