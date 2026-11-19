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


from typing import cast

import httpx
import pytest
from fastmcp import Client, FastMCP

from catalyst_center_mcp.catalyst_client import CatalystCenterClient
from catalyst_center_mcp.config import Settings
from catalyst_center_mcp.tool_loader import load_tools
from catalyst_center_mcp.tool_registry import register_tools


@pytest.mark.asyncio
async def test_issue_pagination_uses_controller_contract() -> None:
    tool = next(tool for tool in load_tools() if tool.name == "api_readIssues")
    queries: list[httpx.QueryParams] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/dna/system/api/v1/auth/token":
            return httpx.Response(200, json={"Token": "fixture-token"})
        assert request.method == "GET"
        assert request.url.path == "/dna/data/api/v1/assuranceIssues"
        query = request.url.params
        queries.append(query)
        limit = int(query["limit"]) if "limit" in query else 10
        offset = int(query["offset"]) if "offset" in query else 1
        return httpx.Response(
            200, json={"response": list(range(offset, min(offset + limit, 27)))}
        )

    settings = Settings(
        base_url="https://controller.invalid", username="test", password="test"
    )
    mcp = FastMCP("test")
    assert (
        register_tools(
            mcp,
            [tool],
            client_factory=lambda: CatalystCenterClient(
                settings, transport=httpx.MockTransport(handle)
            ),
        )
        == 1
    )

    async with Client(mcp) as client:
        listed = await client.list_tools()
        properties = cast(
            dict[str, dict[str, dict[str, list[object]]]], listed[0].input_schema
        )["properties"]
        assert {"minimum": 1, "maximum": 25, "type": "integer"} in properties["limit"][
            "anyOf"
        ]

        response = await client.call_tool(tool.name, {})
        assert not response.is_error
        assert dict(queries[-1]) == {}

        window = {"startTime": 1_780_000_000_000, "endTime": 1_780_000_000_001}
        for offset in (1, 26):
            response = await client.call_tool(
                tool.name, {**window, "limit": 25, "offset": offset}
            )
            assert not response.is_error
            assert dict(queries[-1]) == {
                "startTime": "1780000000000",
                "endTime": "1780000000001",
                "limit": "25",
                "offset": str(offset),
            }
        assert response.structured_content == {"result": '{"response":[26]}'}

        response = await client.call_tool(tool.name, {"limit": 1, "status": "active"})
        assert not response.is_error
        assert dict(queries[-1]) == {"limit": "1", "status": "active"}

        for invalid in ({"limit": 0}, {"limit": 26}, {"limit": 100}, {"offset": 0}):
            response = await client.call_tool(tool.name, invalid, raise_on_error=False)
            assert response.is_error
        assert len(queries) == 4
