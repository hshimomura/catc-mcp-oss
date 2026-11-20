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


import time

import httpx
import pytest
from fastmcp import Client, FastMCP

from catalyst_center_mcp import tool_registry
from catalyst_center_mcp.catalyst_client import CatalystCenterClient
from catalyst_center_mcp.config import Settings, SettingsError
from catalyst_center_mcp.tool_loader import load_tools

ENV = "CATALYST_CENTER_DEVICE_HEALTH_MAX_AGE_DAYS"


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "invalid"])
def test_device_health_window_rejects_invalid_setting(value: str) -> None:
    with pytest.raises(SettingsError, match=ENV):
        _ = Settings.from_env({ENV: value}, require_credentials=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [False, True])
async def test_device_health_end_time_window(
    monkeypatch: pytest.MonkeyPatch, configured: bool
) -> None:
    settings = Settings.from_env(
        {
            "CATALYST_CENTER_HOST": "https://controller.invalid",
            "CATALYST_CENTER_USERNAME": "test",
            "CATALYST_CENTER_PASSWORD": "test",
            **({ENV: "7"} if configured else {}),
        }
    )
    monkeypatch.setattr(tool_registry, "get_settings", lambda: settings)
    device_tool = next(t for t in load_tools() if t.name == "api_devices")
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"Token": "fixture-token"})
        return httpx.Response(200, json={"response": []})

    mcp = FastMCP("test")
    assert (
        tool_registry.register_tools(
            mcp,
            [device_tool],
            client_factory=lambda: CatalystCenterClient(
                settings, transport=httpx.MockTransport(handle)
            ),
        )
        == 1
    )

    now = time.time_ns() // 1_000_000
    async with Client(mcp) as client:
        description = (await client.list_tools())[0].description or ""
        assert ("7 days" in description) is configured
        result = await client.call_tool(
            device_tool.name,
            {"endTime": now - 8 * 86_400_000},
            raise_on_error=False,
        )
        assert result.is_error is configured
        assert len(requests) == (0 if configured else 2)

        recent = await client.call_tool(device_tool.name, {"endTime": now})
        assert not recent.is_error
        latest = await client.call_tool(device_tool.name, {})
        assert not latest.is_error
