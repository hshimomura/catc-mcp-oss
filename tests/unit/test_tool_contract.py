# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0


from pathlib import Path
from typing import cast

import httpx
import pytest
from fastmcp import Client, FastMCP

from catalyst_center_mcp.catalyst_client import CatalystCenterClient
from catalyst_center_mcp.config import Settings
from catalyst_center_mcp.tool_loader import ToolDefinition
from catalyst_center_mcp.tool_registry import register_tools


@pytest.mark.asyncio
async def test_tool_contract(tmp_path: Path) -> None:
    tool = ToolDefinition(
        name="read_example",
        description="Read example data",
        parameters={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["active", "resolved"]},
                "limit": {"type": "integer"},
                "startTime": {"type": "number"},
                "endTime": {"type": "number"},
                "threshold": {"type": "number"},
                "flag": {"type": "boolean", "enum": [True]},
            },
        },
        metadata={"uri": "/api/example", "method": "GET"},
        source_path=tmp_path / "example.json",
    )
    queries: list[httpx.QueryParams] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"Token": "fixture-token"})
        queries.append(request.url.params)
        if request.url.params.get("status") == "resolved":
            return httpx.Response(400, json={"detail": "fixture-detail"})
        return httpx.Response(200, json={"response": []})

    settings = Settings(
        base_url="https://controller.invalid", username="test", password="test"
    )
    mcp = FastMCP("test")
    registered = register_tools(
        mcp,
        [tool],
        client_factory=lambda: CatalystCenterClient(
            settings, transport=httpx.MockTransport(handle)
        ),
    )
    assert registered == 1

    async with Client(mcp) as client:
        args = {
            "startTime": 1_780_000_000_000,
            "endTime": 1_780_000_000_001,
            "threshold": 1.25,
        }
        result = await client.call_tool("read_example", args, raise_on_error=False)
        assert not result.is_error
        assert result.structured_content == {"result": '{"response":[]}'}
        assert dict(queries[0]) == {
            "startTime": "1780000000000",
            "endTime": "1780000000001",
            "threshold": "1.25",
        }

        for invalid in (
            {"status": "unknown"},
            {"flag": False},
            {"limit": "1"},
            {"limit": True},
            {"startTime": 2, "endTime": 1},
        ):
            result = await client.call_tool(
                "read_example", invalid, raise_on_error=False
            )
            assert result.is_error, invalid
        assert len(queries) == 1

        tools = await client.list_tools()
        schema = cast(
            dict[str, dict[str, dict[str, list[object]]]], tools[0].input_schema
        )
        assert {"type": "string", "enum": ["active", "resolved"]} in schema[
            "properties"
        ]["status"]["anyOf"]

        result = await client.call_tool(
            "read_example", {"status": "resolved"}, raise_on_error=False
        )
        assert result.is_error
        text = result.content[0]
        assert text.type == "text"
        assert "400" in text.text
        assert "fixture-detail" not in text.text
        assert len(queries) == 2


@pytest.mark.asyncio
async def test_bundled_tools_remain_discoverable_and_device_health_uses_integer_query() -> (
    None
):
    from catalyst_center_mcp.tool_loader import load_tools

    bundle = load_tools()
    queries: list[httpx.QueryParams] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"Token": "fixture-token"})
        assert request.url.path == "/dna/intent/api/v1/device-health"
        queries.append(request.url.params)
        return httpx.Response(200, json={"response": []})

    mcp = FastMCP("catalog-test")
    settings = Settings(
        base_url="https://controller.invalid", username="test", password="test"
    )
    count = register_tools(
        mcp,
        bundle,
        client_factory=lambda: CatalystCenterClient(
            settings, transport=httpx.MockTransport(handle)
        ),
    )
    async with Client(mcp) as client:
        listed = await client.list_tools()
        assert len(listed) == count
        assert {tool.name for tool in listed} == {tool.name for tool in bundle}
        result = await client.call_tool(
            "api_devices",
            {"startTime": 1_780_000_000_000, "endTime": 1_780_000_000_001},
        )
        assert not result.is_error
        assert dict(queries[0]) == {
            "startTime": "1780000000000",
            "endTime": "1780000000001",
        }
        result = await client.call_tool(
            "api_devices", {"startTime": 1_780_000_000_000.5}, raise_on_error=False
        )
        assert result.is_error
        assert len(queries) == 1
