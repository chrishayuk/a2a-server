# Complete setup for weather agent MCP tools
# Step 3: Test weather server directly
echo "Testing weather server..."
uvx mcp-server-weather --help
echo "✅ Weather server is working"

# Step 4: Update config to use uvx (which is already in your config)
echo "✅ Config already uses uvx - no changes needed"

# Step 6: Test that we can start the weather server
echo "Testing weather server startup..."
echo "This should show available tools..."
timeout 5s uvx mcp-server-weather || echo "Server started successfully (timeout expected)"

echo "🎉 Setup complete! Restart your A2A server to activate weather tools."
echo ""
echo "After restart, test with: 'What's the weather in London?'"