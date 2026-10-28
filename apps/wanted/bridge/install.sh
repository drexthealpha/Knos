#!/bin/sh
# Install the official MCP SDK beside qloo_bridge.mjs, at the exact version Qloo's starter pins
# (Qloo's starter kit, starter/mcp-client/package.json: @modelcontextprotocol/sdk 1.30.1). Nothing is saved to a
# package.json (the repository keeps no JSON files under apps/wanted); node_modules/ is git-ignored.
set -eu
cd "$(dirname "$0")"
npm install --no-save --no-package-lock --no-audit --no-fund --prefix . @modelcontextprotocol/sdk@1.30.1
node -e 'import("@modelcontextprotocol/sdk/client/index.js").then(() => console.log("MCP SDK ready"))'
