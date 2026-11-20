# Catalyst Center MCP

Standalone MCP server for Cisco Catalyst Center auto-generated tools.

This repository intentionally bundles only the generated DNAC tools from
`dialographer-kb/Agent_DNAC/autogen/promoted`. It does not import PyFE at runtime,
does not mount custom tools, and does not delegate generated tool execution to the
Catalyst Center adapter. Tool calls are translated directly into Catalyst Center REST
requests by this server.

## Runtime

Set the Catalyst Center target through environment variables:

```bash
export CATALYST_CENTER_HOST=10.10.10.10
export CATALYST_CENTER_USERNAME=admin
export CATALYST_CENTER_PASSWORD='...'
export CATALYST_CENTER_VERIFY_SSL=false
```

Run locally:

```bash
pip install -e '.[test]'
uvicorn catalyst_center_mcp.main:app --host 0.0.0.0 --port 7001
```

The streamable HTTP MCP endpoint is mounted at:

```text
http://localhost:7001/v1/mcp
```

Health endpoints:

```text
GET /v1/health
GET /v1/readiness
```

## Tool call behavior

Tool calls report Catalyst Center failures as MCP errors. A successful empty
response remains a successful tool call. Controller response bodies are not
included in tool errors.

Generated enumerated arguments are advertised in the MCP schema and validated
before making a request. Integer fields accept JSON integers. Numeric query
arguments retain integer values without a decimal suffix and preserve
fractional values. A numeric query window with both `startTime` and `endTime`
requires `startTime <= endTime`. Device Health takes integer UTC epoch
milliseconds for both time parameters.

### Device Health time window

If your controller enforces a maximum age for Device Health `endTime`, set
`CATALYST_CENTER_DEVICE_HEALTH_MAX_AGE_DAYS` to that positive whole number
of days. The MCP tool advertises the configured limit and rejects older
timestamps before contacting the controller. Leave the variable unset to
let the controller apply its own policy.

### Assurance issue pagination

Use `api_readIssues` to read Assurance issues on Catalyst Center 3.2.3.
The page size `limit` accepts integers from 1 to 25. If omitted, the controller
defaults to 10. Start at `offset=1` and keep the same filters and page size on
subsequent requests. With `limit=25`, use offsets 1, 26, 51, and so on until
the controller returns fewer than 25 records.

These limits follow the [Cisco OpenAPI specification referenced by the
3.2.3 SDK](https://github.com/cisco-en-programmability/catalyst-center-api-specs/blob/9183caa78eb654f95892b54d9aafc2fd73e62d0e/Assurance/CE_Cat_Center_Org-IssuesList-3.2.2-resolved.yaml#L160-L176).

## Bundling Tools

Tool bundles are exported by the `ci-tools` Jenkins helper from checked-out
`dialographer-kb` and `pyfe` repositories. The runtime repo intentionally only
consumes the exported metadata; it does not own the generation rules.

```bash
python /path/to/ci-tools/jenkinsfiles/scripts/catalyst_mcp_bundle.py \
  --kb-dir /path/to/dialographer-kb \
  --pyfe-dir /path/to/pyfe \
  --platform DNAC \
  --release 2.3.7.9 \
  --output catalyst_center_mcp/bundled_tools
```

Validate the resulting bundle:

```bash
python scripts/validate_bundle.py catalyst_center_mcp/bundled_tools/manifest.json
```

Supported version metadata keys include `min_controller_version`,
`max_controller_version`, camelCase variants, and `supportedVersions.min/max`.
The manifest records the ci-tools, PyFE, and dialographer-kb commits used to
produce the bundle.

## Docker

```bash
docker build -t catalyst-center-mcp:local .
docker run --rm -p 7001:7001 \
  -e CATALYST_CENTER_HOST \
  -e CATALYST_CENTER_USERNAME \
  -e CATALYST_CENTER_PASSWORD \
  -e CATALYST_CENTER_VERIFY_SSL=false \
  catalyst-center-mcp:local
```
