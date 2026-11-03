"""Configurable MCP v1 adapter; tool schemas are checked before any generation."""
import asyncio
import json
import os
from contextlib import AsyncExitStack
from datetime import timedelta


def expand(value, values):
    if isinstance(value, dict):
        return {k: expand(v, values) for k,v in value.items()}
    if isinstance(value, list):
        return [expand(v, values) for v in value]
    if isinstance(value, str):
        for k,v in values.items():
            value = value.replace('{{' + k + '}}', str(v))
        if '{{' in value:
            raise ValueError('Çözümlenemeyen MCP argümanı: ' + value)
    return value


def lookup(obj, path):
    if not path:
        return None
    for key in path.split('.'):
        if isinstance(obj, list) and key.isdigit():
            obj = obj[int(key)] if int(key) < len(obj) else None
        elif isinstance(obj, dict):
            obj = obj.get(key)
        else:
            return None
    return obj


def find_key(obj, key):
    """First value stored under key anywhere in a nested result (servers nest ids differently)."""
    if isinstance(obj, dict):
        if obj.get(key):
            return obj[key]
        obj = list(obj.values())
    if isinstance(obj, list):
        for item in obj:
            found = find_key(item, key)
            if found:
                return found
    return None


async def request(cfg, tool=None, arguments=None):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamablehttp_client
    from jsonschema import validate
    async with AsyncExitStack() as stack:
        if cfg['transport'] == 'stdio':
            if not cfg.get('command'):
                raise ValueError('config.json içinde MCP command gerekli.')
            transport = stdio_client(StdioServerParameters(command=cfg['command'],
                args=cfg.get('args', []), env={**os.environ, **cfg.get('env', {})}))
        elif cfg['transport'] == 'http':
            if not cfg.get('url'):
                raise ValueError('config.json içinde MCP url gerekli.')
            headers = {}
            token = os.environ.get(cfg.get('token_env', 'VIDEO_MCP_TOKEN'))
            if token:
                headers['Authorization'] = 'Bearer ' + token
            transport = streamablehttp_client(cfg['url'], headers=headers,
                timeout=timedelta(seconds=cfg.get('timeout_seconds', 900)),
                sse_read_timeout=timedelta(seconds=cfg.get('timeout_seconds', 900)))
        else:
            raise ValueError('MCP transport stdio veya http olmalı.')
        streams = await stack.enter_async_context(transport)
        session = await stack.enter_async_context(ClientSession(streams[0], streams[1],
            read_timeout_seconds=timedelta(seconds=cfg.get('timeout_seconds', 900))))
        await session.initialize()
        listed = []
        cursor = None
        while True:
            page = await session.list_tools(cursor=cursor)
            listed.extend(page.tools)
            cursor = page.nextCursor
            if not cursor:
                break
        if tool is None:
            return [t.model_dump(mode='json') for t in listed]
        selected = next((t for t in listed if t.name == tool), None)
        if selected is None:
            raise ValueError('MCP aracı bulunamadı: ' + tool)
        validate(arguments, selected.inputSchema)
        result = await session.call_tool(tool, arguments=arguments)
        if result.isError:
            raise RuntimeError('MCP aracı hata döndürdü: ' + str(result.content))
        data = getattr(result, 'structuredContent', None)
        if data is not None:
            return data
        texts = [c.text for c in result.content if c.type == 'text']
        try:
            return json.loads('\n'.join(texts))
        except json.JSONDecodeError:
            return {'text': '\n'.join(texts)}


def call(cfg, tool=None, arguments=None):
    return asyncio.run(request(cfg, tool, arguments))
