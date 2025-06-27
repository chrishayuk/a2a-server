# a2a_server/utils/config_debugger.py
"""
Configuration debugging utility to diagnose handler and session setup issues.
"""
import logging
import inspect
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ConfigIssue:
    """Represents a configuration issue."""
    level: str  # 'error', 'warning', 'info'
    component: str  # 'handler', 'agent', 'session', etc.
    message: str
    details: Optional[Dict[str, Any]] = None


class ConfigurationDebugger:
    """
    Comprehensive configuration debugger for A2A server components.
    """
    
    def __init__(self):
        self.issues: List[ConfigIssue] = []
    
    def debug_handler_config(self, handler_name: str, config: Dict[str, Any]) -> List[ConfigIssue]:
        """Debug a handler configuration."""
        self.issues = []
        
        self._check_required_fields(handler_name, config)
        self._check_session_configuration(handler_name, config)
        self._check_agent_configuration(handler_name, config)
        self._check_type_imports(handler_name, config)
        
        return self.issues.copy()
    
    def _check_required_fields(self, handler_name: str, config: Dict[str, Any]) -> None:
        """Check for required configuration fields."""
        required_fields = ['type', 'agent']
        
        for field in required_fields:
            if field not in config:
                self.issues.append(ConfigIssue(
                    level='error',
                    component='handler',
                    message=f"Handler '{handler_name}' missing required field '{field}'",
                    details={'handler': handler_name, 'missing_field': field}
                ))
    
    def _check_session_configuration(self, handler_name: str, config: Dict[str, Any]) -> None:
        """Check session configuration consistency."""
        # Extract session-related fields
        enable_sessions = config.get('enable_sessions')
        session_sharing = config.get('session_sharing')
        shared_sandbox_group = config.get('shared_sandbox_group')
        sandbox_id = config.get('sandbox_id')
        
        # Check for the critical issue: enable_sessions not being passed to agent
        if enable_sessions is not None:
            self.issues.append(ConfigIssue(
                level='info',
                component='session',
                message=f"Handler '{handler_name}' has enable_sessions: {enable_sessions}",
                details={
                    'handler': handler_name,
                    'enable_sessions': enable_sessions,
                    'config_location': 'handler_level'
                }
            ))
        
        # Check session sharing consistency
        if session_sharing and not shared_sandbox_group:
            self.issues.append(ConfigIssue(
                level='warning',
                component='session',
                message=f"Handler '{handler_name}' has session_sharing=True but no shared_sandbox_group",
                details={
                    'handler': handler_name,
                    'session_sharing': session_sharing,
                    'shared_sandbox_group': shared_sandbox_group
                }
            ))
        
        if shared_sandbox_group and not session_sharing:
            self.issues.append(ConfigIssue(
                level='warning',
                component='session',
                message=f"Handler '{handler_name}' has shared_sandbox_group but session_sharing not enabled",
                details={
                    'handler': handler_name,
                    'session_sharing': session_sharing,
                    'shared_sandbox_group': shared_sandbox_group
                }
            ))
        
        # Check for conflicting session settings
        if enable_sessions is False and session_sharing:
            self.issues.append(ConfigIssue(
                level='error',
                component='session',
                message=f"Handler '{handler_name}' has enable_sessions=False but session_sharing=True",
                details={
                    'handler': handler_name,
                    'enable_sessions': enable_sessions,
                    'session_sharing': session_sharing,
                    'recommendation': 'Set enable_sessions=True for session sharing to work'
                }
            ))
    
    def _check_agent_configuration(self, handler_name: str, config: Dict[str, Any]) -> None:
        """Check agent configuration."""
        agent_spec = config.get('agent')
        
        if not agent_spec:
            return
        
        if isinstance(agent_spec, str):
            # Check if it looks like a factory function
            if '.' in agent_spec and agent_spec.count('.') >= 2:
                self.issues.append(ConfigIssue(
                    level='info',
                    component='agent',
                    message=f"Handler '{handler_name}' uses agent factory: {agent_spec}",
                    details={
                        'handler': handler_name,
                        'agent_spec': agent_spec,
                        'type': 'factory_function'
                    }
                ))
                
                # Check if configuration parameters will be passed to factory
                config_params = {k: v for k, v in config.items() 
                               if k not in ['type', 'name', 'agent', 'agent_card']}
                
                if config_params:
                    self.issues.append(ConfigIssue(
                        level='info',
                        component='agent',
                        message=f"Parameters will be passed to agent factory: {list(config_params.keys())}",
                        details={
                            'handler': handler_name,
                            'factory_params': list(config_params.keys()),
                            'param_values': config_params
                        }
                    ))
                    
                    # Check for enable_sessions specifically
                    if 'enable_sessions' in config_params:
                        self.issues.append(ConfigIssue(
                            level='info',
                            component='agent',
                            message=f"enable_sessions={config_params['enable_sessions']} will be passed to agent factory",
                            details={
                                'handler': handler_name,
                                'enable_sessions_value': config_params['enable_sessions'],
                                'expected_behavior': 'Agent should use this value for internal session management'
                            }
                        ))
    
    def _check_type_imports(self, handler_name: str, config: Dict[str, Any]) -> None:
        """Check if handler type can be imported."""
        handler_type = config.get('type')
        
        if not handler_type:
            return
        
        try:
            import importlib
            module_path, _, class_name = handler_type.rpartition('.')
            module = importlib.import_module(module_path)
            handler_class = getattr(module, class_name)
            
            self.issues.append(ConfigIssue(
                level='info',
                component='handler',
                message=f"Handler type '{handler_type}' imported successfully",
                details={
                    'handler': handler_name,
                    'handler_class': str(handler_class),
                    'module': module_path
                }
            ))
            
            # Check constructor signature
            sig = inspect.signature(handler_class.__init__)
            params = list(sig.parameters.keys())
            
            self.issues.append(ConfigIssue(
                level='info',
                component='handler',
                message=f"Handler constructor parameters: {params}",
                details={
                    'handler': handler_name,
                    'constructor_params': params,
                    'accepts_agent': 'agent' in params,
                    'accepts_enable_sessions': 'enable_sessions' in params
                }
            ))
            
        except Exception as e:
            self.issues.append(ConfigIssue(
                level='error',
                component='handler',
                message=f"Cannot import handler type '{handler_type}': {e}",
                details={
                    'handler': handler_name,
                    'handler_type': handler_type,
                    'error': str(e)
                }
            ))


def debug_yaml_configuration(config: Dict[str, Any]) -> Dict[str, List[ConfigIssue]]:
    """
    Debug an entire YAML configuration.
    
    Args:
        config: The parsed YAML configuration
        
    Returns:
        Dictionary mapping handler names to their issues
    """
    debugger = ConfigurationDebugger()
    results = {}
    
    handlers_config = config.get('handlers', {})
    
    # Skip meta fields
    handler_configs = {k: v for k, v in handlers_config.items() 
                      if k not in ['use_discovery', 'default_handler']}
    
    for handler_name, handler_config in handler_configs.items():
        if isinstance(handler_config, dict):
            issues = debugger.debug_handler_config(handler_name, handler_config)
            results[handler_name] = issues
    
    return results


def print_debug_report(issues_by_handler: Dict[str, List[ConfigIssue]]) -> None:
    """Print a formatted debug report."""
    print("\n" + "="*80)
    print("A2A CONFIGURATION DEBUG REPORT")
    print("="*80)
    
    total_errors = 0
    total_warnings = 0
    total_info = 0
    
    for handler_name, issues in issues_by_handler.items():
        if not issues:
            continue
            
        print(f"\n🔧 Handler: {handler_name}")
        print("-" * 40)
        
        for issue in issues:
            icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}[issue.level]
            print(f"{icon} [{issue.level.upper()}] {issue.component}: {issue.message}")
            
            if issue.details:
                for key, value in issue.details.items():
                    print(f"    {key}: {value}")
            
            if issue.level == "error":
                total_errors += 1
            elif issue.level == "warning":
                total_warnings += 1
            else:
                total_info += 1
    
    print(f"\n📊 SUMMARY:")
    print(f"   Errors: {total_errors}")
    print(f"   Warnings: {total_warnings}")
    print(f"   Info: {total_info}")
    
    if total_errors > 0:
        print(f"\n❌ {total_errors} errors found - these must be fixed")
    elif total_warnings > 0:
        print(f"\n⚠️ {total_warnings} warnings found - consider reviewing")
    else:
        print(f"\n✅ Configuration looks good!")
    
    print("="*80)


# Quick debugging function for your specific issue
def debug_session_configuration_issue():
    """
    Debug the specific session configuration issue you're experiencing.
    """
    print("\n🔍 DEBUGGING SESSION CONFIGURATION ISSUE")
    print("="*60)
    
    print("❌ ISSUE: Agents showing 'Internal sessions enabled: False' despite enable_sessions: true")
    print("\n🔧 LIKELY CAUSES:")
    print("1. enable_sessions parameter not being passed to agent factory")
    print("2. Agent factory not using enable_sessions parameter correctly")
    print("3. Handler configuration not applying agent-level settings")
    
    print("\n✅ SOLUTION:")
    print("1. Ensure enable_sessions is in handler config (✓ - you have this)")
    print("2. Ensure discovery.py passes config to agent factory (needs fix)")
    print("3. Ensure agent factory uses enable_sessions parameter (check your agent code)")
    
    print("\n🔧 YAML CONFIG SHOULD LOOK LIKE:")
    print("""
  chuk_pirate:
    type: a2a_server.tasks.handlers.chuk.chuk_agent_handler.AgentHandler
    agent: a2a_server.sample_agents.chuk_pirate.create_pirate_agent
    name: chuk_pirate
    
    # Handler-level session configuration
    sandbox_id: "pirate_sessions"
    session_sharing: true
    shared_sandbox_group: "global_user_sessions"
    
    # 🔧 CRITICAL: Agent-level configuration (passed to factory)
    enable_sessions: true          # ← This must be passed to create_pirate_agent()
    infinite_context: true
    token_threshold: 4000
    """)
    
    print("\n📝 NEXT STEPS:")
    print("1. Update discovery.py to pass config to agent factories (provided)")
    print("2. Verify your agent factory functions use enable_sessions parameter")
    print("3. Test with debug logging enabled")


# Integration with your existing configuration
def integrate_configuration_debugging():
    """Show how to integrate this debugging into your existing setup."""
    print("\n🔧 INTEGRATION GUIDE:")
    print("="*50)
    
    print("1. Add to your main application startup:")
    print("""
from a2a_server.utils.config_debugger import debug_yaml_configuration, print_debug_report

# After loading YAML config
config = yaml.load(config_file)
debug_results = debug_yaml_configuration(config)
print_debug_report(debug_results)
""")
    
    print("\n2. Add debug logging to handler registration:")
    print("""
import logging
logging.getLogger('a2a_server.tasks.discovery').setLevel(logging.DEBUG)
logging.getLogger('a2a_server.sample_agents').setLevel(logging.DEBUG)
""")


if __name__ == "__main__":
    debug_session_configuration_issue()
    integrate_configuration_debugging()


__all__ = [
    "ConfigurationDebugger",
    "ConfigIssue", 
    "debug_yaml_configuration",
    "print_debug_report",
    "debug_session_configuration_issue"
]