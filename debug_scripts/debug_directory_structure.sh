#!/bin/bash

echo "🔍 Checking your actual directory structure..."

echo ""
echo "📁 Looking for a2a_server directories:"
find . -name "a2a_server" -type d

echo ""
echo "📄 Looking for google_adk_handler.py:"
find . -name "google_adk_handler.py" -type f

echo ""
echo "📁 Checking if src/ directory exists:"
if [ -d "src" ]; then
    echo "✅ src/ directory exists"
    echo "Contents of src/:"
    ls -la src/
    
    if [ -d "src/a2a_server" ]; then
        echo "✅ src/a2a_server/ exists"
    else
        echo "❌ src/a2a_server/ does not exist"
    fi
else
    echo "❌ src/ directory does not exist"
fi

echo ""
echo "📁 Checking if a2a_server/ in root exists:"
if [ -d "a2a_server" ]; then
    echo "✅ a2a_server/ directory exists in root"
    echo "Contents of a2a_server/:"
    ls -la a2a_server/ | head -10
else
    echo "❌ a2a_server/ directory does not exist in root"
fi

echo ""
echo "🎯 Based on your working 'pytest tests/tasks' command,"
echo "your code is likely in the ROOT directory, not src/"