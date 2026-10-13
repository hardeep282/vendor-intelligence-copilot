"""Load production secrets from AWS SSM Parameter Store at start-up.

Purpose : production keys never live in images, repos or CI variables. The server reads them
          with its own instance role when the app starts (ADR-004).
Inputs  : an SSM path prefix such as /vendor-copilot/prod and an AWS region.
Outputs : one environment variable per parameter, named after the last path segment
          (/vendor-copilot/prod/ANTHROPIC_API_KEY -> ANTHROPIC_API_KEY).
"""

from __future__ import annotations

import os
from typing import Any


def fetch_parameters(client: Any, prefix: str) -> dict[str, str]:
    """Read every parameter directly under `prefix`, decrypting SecureStrings.

    SSM returns at most 10 parameters per call, so we follow NextToken until it runs out.
    """
    found: dict[str, str] = {}
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Path": prefix, "Recursive": False, "WithDecryption": True}
        if token:
            kwargs["NextToken"] = token
        resp = client.get_parameters_by_path(**kwargs)
        for param in resp.get("Parameters", []):
            name = str(param["Name"]).rsplit("/", 1)[-1].upper()
            found[name] = str(param["Value"])
        token = resp.get("NextToken")
        if not token:
            return found


def load_into_environ(prefix: str, region: str, client: Any | None = None) -> list[str]:
    """Fetch the parameters and export them as environment variables.

    Returns the parameter NAMES that were loaded, never the values, so it is safe to log.
    """
    if client is None:
        import boto3  # imported here so dev and tests never need AWS credentials

        client = boto3.client("ssm", region_name=region)
    params = fetch_parameters(client, prefix)
    for name, value in params.items():
        os.environ[name] = value
    return sorted(params)
