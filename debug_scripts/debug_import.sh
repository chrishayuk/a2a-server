# Test the import
python -c "
import sys
sys.path.insert(0, 'src')
try:
    from a2a_server.tasks.handlers.adk.google_adk_protocol import GoogleADKAgentProtocol
    print('✅ Protocol import works!')
    print(f'Protocol: {GoogleADKAgentProtocol}')
except ImportError as e:
    print(f'❌ Protocol import failed: {e}')
    import traceback
    traceback.print_exc()
"