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

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from inspect import Parameter, Signature
from typing import Annotated, Literal, cast
from urllib.parse import quote

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field, StrictFloat, StrictInt
from pydantic.fields import FieldInfo

from catalyst_center_mcp.catalyst_client import (
    CatalystCenterClient,
    CatalystCenterError,
    RequestPayload,
)
from catalyst_center_mcp.config import get_settings
from catalyst_center_mcp.tool_loader import ToolDefinition

logger = logging.getLogger(__name__)


ClientFactory = Callable[[], CatalystCenterClient]
ToolFunction = Callable[..., Awaitable[str]]


class CatalystMCPTool:
    def __init__(self, mcp_instance: FastMCP) -> None:
        self.mcp: FastMCP = mcp_instance

    def tool(
        self,
        *,
        name: str,
        description: str,
        input_schema: dict[str, object],
        metadata: dict[str, object] | None = None,
    ) -> Callable[[ToolFunction], ToolFunction]:
        def decorator(func: ToolFunction) -> ToolFunction:
            signature, annotations, argument_aliases = _signature_from_schema(
                input_schema
            )

            async def generated_tool_wrapper(**kwargs: object) -> str:
                restored_kwargs = {
                    argument_aliases.get(key, key): value
                    for key, value in kwargs.items()
                }
                return await func(**restored_kwargs)

            generated_tool_wrapper.__name__ = _safe_identifier(name)
            generated_tool_wrapper.__doc__ = description
            generated_tool_wrapper.__signature__ = signature
            generated_tool_wrapper.__annotations__ = annotations

            _ = self.mcp.tool(
                name=name,
                description=description,
                meta=metadata,
            )(generated_tool_wrapper)
            return generated_tool_wrapper

        return decorator


def _safe_identifier(name: str) -> str:
    value = re.sub(r"\W", "_", name)
    if not value or value[0].isdigit():
        value = f"_{value}"
    return value


def _unique_identifier(name: str, used: set[str]) -> str:
    base = _safe_identifier(name)
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def _python_type_from_schema(schema: dict[str, object]) -> object:
    choices = schema.get("enum")
    if isinstance(choices, list):
        values = tuple(cast(list[object], choices))
        if values and all(type(value) in (str, bool, int) for value in values):
            return Literal[values]

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next(
            (item for item in cast(list[object], schema_type) if item != "null"), None
        )

    if schema_type == "string":
        return str
    if schema_type == "integer":
        return StrictInt
    if schema_type == "number":
        return StrictInt | StrictFloat
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        return list[object]
    if schema_type == "object":
        return dict[str, object]
    return object


def _field_from_schema(
    schema: dict[str, object], *, alias: str | None = None
) -> FieldInfo:
    return cast(
        FieldInfo,
        Field(
            alias=alias,
            description=cast(str | None, schema.get("description")),
            ge=cast(int | float | None, schema.get("minimum")),
            le=cast(int | float | None, schema.get("maximum")),
            min_length=cast(int | None, schema.get("minLength")),
            max_length=cast(int | None, schema.get("maxLength")),
        ),
    )


def _signature_from_schema(
    input_schema: dict[str, object],
) -> tuple[Signature, dict[str, object], dict[str, str]]:
    properties = input_schema.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    required = input_schema.get("required")
    required_names: set[str] = (
        set(cast(list[str], required)) if isinstance(required, list) else set()
    )

    parameters: list[Parameter] = []
    annotations: dict[str, object] = {"return": str}
    aliases: dict[str, str] = {}
    used_names: set[str] = set()

    for original_name, property_schema in cast(dict[str, object], properties).items():
        schema = (
            cast(dict[str, object], property_schema)
            if isinstance(property_schema, dict)
            else {}
        )
        parameter_name = _unique_identifier(str(original_name), used_names)
        aliases[parameter_name] = str(original_name)
        is_required = original_name in required_names
        base_type = _python_type_from_schema(schema)
        if not is_required:
            base_type = cast(type[object], base_type) | None
        alias = str(original_name) if parameter_name != original_name else None
        annotation = Annotated[base_type, _field_from_schema(schema, alias=alias)]
        default = Parameter.empty if is_required else None
        parameters.append(
            Parameter(
                parameter_name,
                Parameter.KEYWORD_ONLY,
                default=default,
                annotation=annotation,
            )
        )
        annotations[parameter_name] = annotation

    return (
        Signature(parameters=parameters, return_annotation=str),
        annotations,
        aliases,
    )


def _json_result(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _drop_none_values(values: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in values.items() if value is not None}


def _replace_path_params(uri: str, path_params: dict[str, object]) -> str:
    path = uri
    for key, value in path_params.items():
        token = "{" + key + "}"
        path = path.replace(token, quote(str(value), safe=""))
    return path


def build_request_payload(
    tool: ToolDefinition, arguments: dict[str, object]
) -> RequestPayload:
    metadata: dict[str, object] = tool.metadata
    uri = metadata.get("uri") or metadata.get("path")
    method = metadata.get("method")
    if not isinstance(uri, str) or not uri or not isinstance(method, str) or not method:
        raise ValueError(
            f"Tool {tool.name} is missing additionalMetadata.uri or method"
        )

    filtered_args = _drop_none_values(arguments)
    parameter_locations: object = (
        metadata.get("parameterLocation") or metadata.get("parameter_location") or {}
    )
    locations = (
        cast(dict[str, object], parameter_locations)
        if isinstance(parameter_locations, dict)
        else {}
    )

    query: dict[str, object] = {}
    headers: dict[str, str] = {}
    body_fields: dict[str, object] = {}
    path_params: dict[str, object] = {}

    for key, value in filtered_args.items():
        location = str(locations.get(key) or "").lower()
        if location in {"path", "pathparam", "path_parameter"}:
            path_params[key] = value
        elif location in {"header", "headers"}:
            headers[key] = str(value)
        elif location in {"body", "requestbody", "json"}:
            body_fields[key] = value
        elif location in {
            "query",
            "queryparam",
            "query_parameter",
        } or method.upper() in {"GET", "DELETE"}:
            query[key] = value
        else:
            body_fields[key] = value

    path = _replace_path_params(str(uri), path_params)
    json_body: object = body_fields or None
    if len(body_fields) == 1 and "request" in body_fields:
        json_body = body_fields["request"]

    return RequestPayload(
        method=str(method),
        path=path,
        query=query or None,
        json_body=json_body,
        headers=headers or None,
    )


def _default_client_factory() -> CatalystCenterClient:
    return CatalystCenterClient(get_settings())


def register_tools(
    mcp: FastMCP,
    tools: list[ToolDefinition],
    *,
    client_factory: ClientFactory = _default_client_factory,
) -> int:
    decorator = CatalystMCPTool(mcp)
    registered = 0
    seen: set[str] = set()

    for tool in tools:
        if tool.name in seen:
            raise ValueError(f"Duplicate tool name {tool.name!r}")
        seen.add(tool.name)

        async def execute_tool(_tool: ToolDefinition = tool, **kwargs: object) -> str:
            payload = build_request_payload(_tool, kwargs)
            query: dict[str, object] = payload.query or {}
            start, end = query.get("startTime"), query.get("endTime")
            if (
                isinstance(start, (int, float))
                and isinstance(end, (int, float))
                and start > end
            ):
                raise ToolError("startTime must be less than or equal to endTime.")

            client = client_factory()
            try:
                result = cast(object, await client.request(payload))
                return _json_result(result)
            except CatalystCenterError as exc:
                summary = str(exc).partition(":")[0]
                logger.warning(
                    "Catalyst Center tool %s failed: %s", _tool.name, summary
                )
                raise ToolError(summary) from None
            except Exception:
                logger.exception("Tool %s failed", _tool.name)
                raise ToolError(f"Catalyst Center tool {_tool.name} failed.") from None
            finally:
                await client.aclose()

        _ = decorator.tool(
            name=tool.name,
            description=tool.description,
            input_schema=tool.parameters,
            metadata=tool.metadata,
        )(execute_tool)
        registered += 1

    return registered
