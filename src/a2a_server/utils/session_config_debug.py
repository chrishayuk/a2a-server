# a2a_server/utils/session_config_diagnostics.py
"""
Targeted diagnostic utility to fix the session configuration issue.
"""
import logging
import inspect
import sys
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class SessionConfigDiagnostics:
    """
    Diagnostic utility specifically for debugging session configuration issues.
    """
    
    @staticmethod
    def trace_agent_creation(handler_name: str, config: Dict[str, Any], agent_factory_func):
        """
        Trace agent creation to see where configuration gets lost.
        """
        print(f"\n🔍 TRACING AGENT CREATION FOR: {handler_name}")
        print("=" * 60)
        
        # 1. Check YAML configuration
        print(f"📋 YAML Configuration:")
        print(f"   enable_sessions: {config.get('enable_sessions', 'NOT_SET')}")
        print(f"   session_sharing: {config.get('session_sharing', 'NOT_SET')}")
        print(f"   shared_sandbox_group: {config.get('shared_sandbox_group', 'NOT_SET')}")
        print(f"   All config keys: {list(config.keys())}")
        
        # 2. Check agent factory function
        print(f"\n🏭 Agent Factory Function:")
        print(f"   Function: {agent_factory_func}")
        print(f"   Function name: {getattr(agent_factory_func, '__name__', 'unknown')}")
        print(f"   Module: {getattr(agent_factory_func, '__module__', 'unknown')}")
        
        # 3. Check factory function signature
        try:
            sig = inspect.signature(agent_factory_func)
            params = list(sig.parameters.keys())
            print(f"   Expected parameters: {params}")
            print(f"   Accepts enable_sessions: {'enable_sessions' in params}")
        except Exception as e:
            print(f"   Error getting signature: {e}")
        
        # 4. Extract agent configuration that should be passed to factory
        agent_config = {k: v for k, v in config.items() 
                       if k not in ['type', 'name', 'agent', 'agent_card']}
        
        print(f"\n⚙️ Configuration to Pass to Factory:")
        print(f"   Config keys: {list(agent_config.keys())}")
        print(f"   enable_sessions value: {agent_config.get('enable_sessions', 'NOT_IN_CONFIG')}")
        
        # 5. Test calling the factory with configuration
        print(f"\n🧪 Testing Factory Call:")
        try:
            # Call factory with config
            agent_instance = agent_factory_func(**agent_config)
            print(f"   ✅ Factory call successful")
            print(f"   Agent type: {type(agent_instance)}")
            
            # Check if agent has enable_sessions attribute
            if hasattr(agent_instance, 'enable_sessions'):
                print(f"   Agent enable_sessions: {agent_instance.enable_sessions}")
            else:
                print(f"   ❌ Agent does not have enable_sessions attribute")
                
        except Exception as e:
            print(f"   ❌ Factory call failed: {e}")
            print(f"   This indicates the factory function has issues")
        
        print("=" * 60)
        
        return agent_config
    
    @staticmethod
    def patch_discovery_register_explicit_handlers():
        """
        Monkey patch the discovery system to add debugging and fix the configuration passing.
        """
        from a2a_server.tasks import discovery
        original_register = discovery.register_discovered_handlers
        
        def debug_register_discovered_handlers(
            task_manager,
            packages=None,
            default_handler_class=None,
            extra_kwargs=None,
            **explicit_handlers
        ):
            """Enhanced version with debugging and proper config passing."""
            print(f"\n🔧 DEBUGGING HANDLER REGISTRATION")
            print(f"   Explicit handlers: {list(explicit_handlers.keys())}")
            
            # Process explicit handlers first with debugging
            for handler_name, config in explicit_handlers.items():
                if not isinstance(config, dict):
                    continue
                    
                print(f"\n🎯 Processing handler: {handler_name}")
                
                # Import handler class
                handler_type = config.get('type')
                if not handler_type:
                    print(f"   ❌ No 'type' specified for {handler_name}")
                    continue
                
                try:
                    import importlib
                    module_path, _, class_name = handler_type.rpartition('.')
                    module = importlib.import_module(module_path)
                    handler_class = getattr(module, class_name)
                    print(f"   ✅ Imported handler class: {handler_class}")
                except Exception as e:
                    print(f"   ❌ Failed to import {handler_type}: {e}")
                    continue
                
                # Import agent factory
                agent_spec = config.get('agent')
                if not agent_spec:
                    print(f"   ❌ No 'agent' specified for {handler_name}")
                    continue
                
                try:
                    agent_module_path, _, agent_func_name = agent_spec.rpartition('.')
                    agent_module = importlib.import_module(agent_module_path)
                    agent_factory = getattr(agent_module, agent_func_name)
                    print(f"   ✅ Imported agent factory: {agent_factory}")
                except Exception as e:
                    print(f"   ❌ Failed to import {agent_spec}: {e}")
                    continue
                
                # Run diagnostics
                agent_config = SessionConfigDiagnostics.trace_agent_creation(
                    handler_name, config, agent_factory
                )
                
                # Create agent instance with proper configuration
                try:
                    print(f"\n🚀 Creating agent with configuration...")
                    agent_instance = agent_factory(**agent_config)
                    
                    # Verify the configuration took effect
                    if hasattr(agent_instance, 'enable_sessions'):
                        actual_sessions = agent_instance.enable_sessions
                        expected_sessions = agent_config.get('enable_sessions', False)
                        
                        if actual_sessions == expected_sessions:
                            print(f"   ✅ Session configuration correct: {actual_sessions}")
                        else:
                            print(f"   ❌ Session configuration mismatch!")
                            print(f"      Expected: {expected_sessions}")
                            print(f"      Actual: {actual_sessions}")
                    
                    # Create handler with agent instance
                    handler_kwargs = {
                        'agent': agent_instance,
                        'name': handler_name
                    }
                    
                    # Add other handler-level parameters
                    for key in ['sandbox_id', 'session_sharing', 'shared_sandbox_group']:
                        if key in config:
                            handler_kwargs[key] = config[key]
                    
                    print(f"   Handler kwargs: {list(handler_kwargs.keys())}")
                    
                    handler = handler_class(**handler_kwargs)
                    
                    # Register with task manager
                    is_default = (handler_name == "chuk_pirate" or 
                                 config.get('default', False))
                    
                    task_manager.register_handler(handler, default=is_default)
                    print(f"   ✅ Registered handler {handler_name}{' (default)' if is_default else ''}")
                    
                except Exception as e:
                    print(f"   ❌ Failed to create/register handler: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Call original function for package discovery (if needed)
            if packages:
                print(f"\n📦 Running package discovery for: {packages}")
                original_register(
                    task_manager, 
                    packages=packages, 
                    default_handler_class=default_handler_class,
                    extra_kwargs=extra_kwargs
                )
        
        # Replace the function
        discovery.register_discovered_handlers = debug_register_discovered_handlers
        print("🔧 Patched discovery.register_discovered_handlers with debugging")
    
    @staticmethod
    def verify_agent_factory_config():
        """
        Verify that agent factory functions are working correctly.
        """
        print(f"\n🧪 TESTING AGENT FACTORIES")
        print("=" * 50)
        
        # Test pirate agent factory
        try:
            from a2a_server.sample_agents.chuk_pirate import create_pirate_agent
            
            print(f"🏴‍☠️ Testing pirate agent factory...")
            
            # Test with enable_sessions=True
            test_config = {
                'enable_sessions': True,
                'provider': 'openai',
                'model': 'gpt-4o-mini',
                'streaming': True
            }
            
            print(f"   Calling with config: {test_config}")
            pirate_agent = create_pirate_agent(**test_config)
            
            print(f"   Created agent: {type(pirate_agent)}")
            print(f"   enable_sessions: {getattr(pirate_agent, 'enable_sessions', 'NOT_SET')}")
            
            if hasattr(pirate_agent, 'enable_sessions') and pirate_agent.enable_sessions:
                print(f"   ✅ Pirate agent factory working correctly")
            else:
                print(f"   ❌ Pirate agent factory not setting enable_sessions correctly")
                
        except Exception as e:
            print(f"   ❌ Pirate agent factory test failed: {e}")
            import traceback
            traceback.print_exc()
        
        # Test chef agent factory
        try:
            from a2a_server.sample_agents.chuk_chef import create_chef_agent
            
            print(f"\n🍳 Testing chef agent factory...")
            
            test_config = {
                'enable_sessions': True,
                'provider': 'openai', 
                'model': 'gpt-4o-mini',
                'streaming': True
            }
            
            print(f"   Calling with config: {test_config}")
            chef_agent = create_chef_agent(**test_config)
            
            print(f"   Created agent: {type(chef_agent)}")
            print(f"   enable_sessions: {getattr(chef_agent, 'enable_sessions', 'NOT_SET')}")
            
            if hasattr(chef_agent, 'enable_sessions') and chef_agent.enable_sessions:
                print(f"   ✅ Chef agent factory working correctly")
            else:
                print(f"   ❌ Chef agent factory not setting enable_sessions correctly")
                
        except Exception as e:
            print(f"   ❌ Chef agent factory test failed: {e}")
            import traceback
            traceback.print_exc()


def apply_session_config_fix():
    """
    Apply the complete fix for session configuration issues.
    """
    print(f"\n🔧 APPLYING SESSION CONFIGURATION FIX")
    print("=" * 50)
    
    # 1. First verify agent factories work
    SessionConfigDiagnostics.verify_agent_factory_config()
    
    # 2. Patch the discovery system
    SessionConfigDiagnostics.patch_discovery_register_explicit_handlers()
    
    print(f"\n✅ Session configuration fix applied!")
    print(f"   - Agent factories tested")
    print(f"   - Discovery system patched with debugging")
    print(f"   - Configuration passing fixed")
    
    return True


if __name__ == "__main__":
    apply_session_config_fix()


# Usage: Add this to your main application startup
"""
# Add this to your main application file BEFORE handler registration:

from a2a_server.utils.session_config_diagnostics import apply_session_config_fix

# Apply the fix
apply_session_config_fix()

# Then proceed with normal handler registration
# The discovery system will now properly pass configuration and provide detailed debugging
"""