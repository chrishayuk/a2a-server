# a2a/json_rpc/models.py
# Pydantic wire models for JSON-RPC 2.0 messages (requests & responses).

from typing import Any, Dict, Literal, Union
from pydantic import BaseModel, Field, ConfigDict

Json = Dict[str, Any]
ReqId = Union[int, str, None]


class Request(BaseModel):
    """JSON-RPC 2.0 Request object."""
    model_config = ConfigDict()

    jsonrpc: Literal["2.0"] = Field(
        "2.0",
        description="JSON-RPC protocol version."
    )
    id: ReqId = Field(
        None,
        description="Unique request identifier. Omit or set to null for notifications."
    )
    method: str = Field(
        ..., description="Name of the method to invoke."
    )
    params: Any = Field(
        None,
        description="Parameters for the method. May be omitted."
    )


class Response(BaseModel):
    """JSON-RPC 2.0 Response object."""
    model_config = ConfigDict(validate_default=True)

    jsonrpc: Literal["2.0"] = Field(
        "2.0",
        description="JSON-RPC protocol version."
    )
    id: ReqId = Field(
        ..., description="Identifier of the corresponding request."
    )
    result: Any | None = Field(
        None,
        description="Result value if the request was successful."
    )
    error: Json | None = Field(
        None,
        description="Error object if the request failed."
    )
