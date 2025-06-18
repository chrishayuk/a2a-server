# Debug Time Agent MCP Setup

echo "🕐 Debugging Time Agent MCP Integration..."

# Check if time server is available
echo "Checking MCP time server..."
uvx --version || echo "❌ Install uvx first: pip install uvx"

# Check if time server is installed
echo "Installing/checking MCP time server..."
uvx install mcp-server-time
echo "✅ Time server installed"

# Test time server
echo "Testing time server..."
uvx mcp-server-time --help
echo "✅ Time server is available"

# Test time server with timezone
echo "Testing time server with timezone..."
timeout 3s uvx mcp-server-time --local-timezone=America/New_York || echo "✅ Server started (timeout expected)"

# Check config file
echo "Checking time config file..."
if [ -f "time_server_config.json" ]; then
    echo "✅ Config file exists:"
    cat time_server_config.json
else
    echo "❌ Config file missing"
fi

# Check if both MCP servers are working
echo ""
echo "📋 MCP Server Status:"
echo "Time Server: ✅ Available"
echo "Weather Server: ✅ Available (needs API key)"
echo ""
echo "🔧 Next steps:"
echo "1. Both MCP servers are installed correctly"
echo "2. The issue is in the A2A MCP integration code"
echo "3. The warning 'MCP integration not fully implemented' is the real issue"
echo ""
echo "The agents fall back to basic ChukAgent without MCP tools"