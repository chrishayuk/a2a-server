"""
Global pytest configuration to ensure proper import paths for src/ layout.
"""
import sys
import os
from pathlib import Path

# Get the project root directory (parent of tests/)
project_root = Path(__file__).parent.parent

# Add src directory to Python path at the very beginning
src_path = project_root / "src"
if src_path.exists() and str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
    print(f"Added {src_path} to Python path")

# Also add the project root as a fallback
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
    print(f"Added {project_root} to Python path")

# Debug info - shows what paths are available
print(f"Python path (first 5 entries): {sys.path[:5]}")

# Verify we can import the main package
try:
    import a2a_server
    print(f"✅ Successfully imported a2a_server from: {a2a_server.__file__}")
except ImportError as e:
    print(f"❌ Failed to import a2a_server: {e}")

# Test if we can import the ADK package specifically
try:
    import a2a_server.tasks.handlers.adk
    print(f"✅ Successfully imported ADK package from: {a2a_server.tasks.handlers.adk.__file__}")
except ImportError as e:
    print(f"❌ Failed to import ADK package: {e}")

# Test if we can import the protocol specifically
try:
    from a2a_server.tasks.handlers.adk.google_adk_protocol import GoogleADKAgentProtocol
    print(f"✅ Successfully imported GoogleADKAgentProtocol")
except ImportError as e:
    print(f"❌ Failed to import GoogleADKAgentProtocol: {e}")
    
    # Try to see what's actually in the ADK directory
    adk_path = src_path / "a2a_server" / "tasks" / "handlers" / "adk"
    if adk_path.exists():
        print(f"📁 ADK directory exists at: {adk_path}")
        print(f"📄 Files in ADK directory: {list(adk_path.glob('*.py'))}")
    else:
        print(f"❌ ADK directory does not exist at: {adk_path}")

print("-" * 60)