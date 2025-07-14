#!/usr/bin/env python3
"""
A2A Server Diagnostic Script
============================

This script diagnoses issues with A2A server handler registration and configuration.
It simulates the startup process and identifies where things go wrong.

Usage:
    python diagnose_a2a.py [config_file]
    
    If no config file specified, looks for:
    - agent.yaml
    - config.yaml
    - a2a_config.yaml
"""

import asyncio
import importlib
import inspect
import json
import logging
import os
import sys
import traceback
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

# Configure logging for diagnostics
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)8s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('a2a_diagnostic')

class DiagnosticResults:
    """Container for diagnostic results."""
    def __init__(self):
        self.issues = []
        self.warnings = []
        self.successes = []
        self.config = None
        self.discovered_handlers = []
        self.import_errors = []
        
    def add_issue(self, message: str, details: str = None):
        self.issues.append({"message": message, "details": details})
        
    def add_warning(self, message: str, details: str = None):
        self.warnings.append({"message": message, "details": details})
        
    def add_success(self, message: str, details: str = None):
        self.successes.append({"message": message, "details": details})

class A2ADiagnostic:
    """Main diagnostic class."""
    
    def __init__(self, config_file: Optional[str] = None):
        self.config_file = config_file
        self.results = DiagnosticResults()
        
    def find_config_file(self) -> Optional[str]:
        """Find the configuration file."""
        if self.config_file and os.path.exists(self.config_file):
            return self.config_file
            
        candidates = ['agent.yaml', 'config.yaml', 'a2a_config.yaml']
        for candidate in candidates:
            if os.path.exists(candidate):
                logger.info(f"Found config file: {candidate}")
                return candidate
                
        return None
    
    def load_config(self, config_file: str) -> Dict[str, Any]:
        """Load and validate configuration."""
        try:
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)
            
            self.results.add_success(f"Successfully loaded config from {config_file}")
            self.results.config = config
            return config
            
        except yaml.YAMLError as e:
            self.results.add_issue(f"YAML parsing error in {config_file}", str(e))
            return {}
        except Exception as e:
            self.results.add_issue(f"Failed to load config file {config_file}", str(e))
            return {}
    
    def check_python_environment(self):
        """Check Python environment and imports."""
        logger.info("🔍 Checking Python environment...")
        
        # Check Python version
        if sys.version_info < (3, 11):
            self.results.add_warning(
                f"Python {sys.version} detected. A2A recommends Python 3.11+",
                "Some features may not work correctly"
            )
        else:
            self.results.add_success(f"Python version: {sys.version}")
        
        # Check critical imports
        critical_modules = [
            'a2a_server',
            'a2a_server.app',
            'a2a_server.tasks.task_manager',
            'a2a_server.tasks.discovery',
            'a2a_server.tasks.handlers.task_handler',
            'a2a_server.tasks.handlers.echo_handler',
        ]
        
        for module_name in critical_modules:
            try:
                importlib.import_module(module_name)
                self.results.add_success(f"✅ {module_name}")
            except ImportError as e:
                self.results.add_issue(f"❌ Cannot import {module_name}", str(e))
                self.results.import_errors.append(module_name)
    
    def analyze_handlers_config(self, config: Dict[str, Any]):
        """Analyze the handlers configuration section."""
        logger.info("🔍 Analyzing handlers configuration...")
        
        handlers_config = config.get('handlers', {})
        if not handlers_config:
            self.results.add_issue("No 'handlers' section found in configuration")
            return
            
        self.results.add_success("Found 'handlers' section in configuration")
        
        # Check use_discovery setting
        use_discovery = handlers_config.get('use_discovery', False)
        self.results.add_success(f"use_discovery: {use_discovery}")
        
        # Check default_handler setting
        default_handler = handlers_config.get('default_handler')
        if default_handler:
            self.results.add_success(f"default_handler: {default_handler}")
        else:
            self.results.add_warning("No default_handler specified")
        
        # Check handler_packages for discovery
        if use_discovery:
            handler_packages = handlers_config.get('handler_packages', [])
            if handler_packages:
                self.results.add_success(f"handler_packages: {handler_packages}")
            else:
                self.results.add_warning("use_discovery=true but no handler_packages specified")
        
        # Analyze individual handler configurations
        handler_configs = {
            k: v for k, v in handlers_config.items() 
            if k not in ['use_discovery', 'default_handler', 'handler_packages'] and isinstance(v, dict)
        }
        
        if handler_configs:
            self.results.add_success(f"Found {len(handler_configs)} handler configurations: {list(handler_configs.keys())}")
            for name, config in handler_configs.items():
                self.analyze_handler_config(name, config)
        else:
            if not use_discovery:
                self.results.add_issue("No handler configurations found and use_discovery=false")
    
    def analyze_handler_config(self, name: str, config: Dict[str, Any]):
        """Analyze a specific handler configuration."""
        logger.info(f"🔍 Analyzing handler: {name}")
        
        # Check required fields
        handler_type = config.get('type')
        if not handler_type:
            self.results.add_issue(f"Handler '{name}' missing 'type' field")
            return
            
        self.results.add_success(f"Handler '{name}' type: {handler_type}")
        
        # Try to import the handler class
        try:
            module_path, _, class_name = handler_type.rpartition('.')
            module = importlib.import_module(module_path)
            handler_class = getattr(module, class_name)
            self.results.add_success(f"✅ Handler class {class_name} imported successfully")
            
            # Check if it's agent-based
            is_agent_based = self.check_if_agent_based_handler(handler_class)
            if is_agent_based:
                self.results.add_success(f"Handler '{name}' is agent-based")
                self.check_agent_config(name, config)
            else:
                self.results.add_success(f"Handler '{name}' is standalone")
                
        except ImportError as e:
            self.results.add_issue(f"Cannot import handler class '{handler_type}'", str(e))
        except AttributeError as e:
            self.results.add_issue(f"Handler class '{class_name}' not found in module '{module_path}'", str(e))
        except Exception as e:
            self.results.add_issue(f"Error analyzing handler '{name}'", str(e))
    
    def check_if_agent_based_handler(self, handler_class: Type) -> bool:
        """Check if a handler class is agent-based."""
        try:
            # Check constructor signature for 'agent' parameter
            sig = inspect.signature(handler_class.__init__)
            params = sig.parameters
            
            if 'agent' in params:
                agent_param = params['agent']
                if agent_param.default is inspect.Parameter.empty:
                    return True
                    
            # Check class hierarchy for known agent-based classes
            for base_class in inspect.getmro(handler_class):
                class_name = base_class.__name__
                if class_name in ['GoogleADKHandler', 'ChukAgentHandler', 'AgentHandler']:
                    return True
                    
            return False
            
        except Exception:
            return False
    
    def check_agent_config(self, handler_name: str, config: Dict[str, Any]):
        """Check agent configuration for agent-based handlers."""
        agent_spec = config.get('agent')
        if not agent_spec:
            self.results.add_issue(f"Agent-based handler '{handler_name}' missing 'agent' configuration")
            return
            
        if isinstance(agent_spec, str):
            # Check if agent factory function exists
            try:
                module_path, _, func_name = agent_spec.rpartition('.')
                module = importlib.import_module(module_path)
                agent_factory = getattr(module, func_name)
                
                if callable(agent_factory):
                    self.results.add_success(f"✅ Agent factory '{func_name}' found and callable")
                    
                    # Check if we can call it with the provided config
                    agent_config = {k: v for k, v in config.items() 
                                   if k not in ['type', 'name', 'agent', 'agent_card']}
                    
                    try:
                        # Get function signature
                        sig = inspect.signature(agent_factory)
                        params = set(sig.parameters.keys())
                        
                        # Check if all config keys are valid parameters
                        invalid_params = set(agent_config.keys()) - params
                        if invalid_params:
                            self.results.add_warning(
                                f"Agent factory '{func_name}' doesn't accept parameters: {invalid_params}",
                                f"Valid parameters: {params}"
                            )
                        else:
                            self.results.add_success(f"All agent config parameters are valid for '{func_name}'")
                            
                    except Exception as e:
                        self.results.add_warning(f"Could not inspect agent factory signature", str(e))
                        
                else:
                    self.results.add_success(f"Agent spec '{agent_spec}' found (not a factory function)")
                    
            except ImportError as e:
                self.results.add_issue(f"Cannot import agent module '{module_path}'", str(e))
            except AttributeError as e:
                self.results.add_issue(f"Agent factory '{func_name}' not found in module '{module_path}'", str(e))
            except Exception as e:
                self.results.add_issue(f"Error checking agent spec '{agent_spec}'", str(e))
        else:
            self.results.add_success(f"Agent spec is not a string (direct object): {type(agent_spec)}")
    
    def test_discovery_process(self, config: Dict[str, Any]):
        """Test the handler discovery process."""
        logger.info("🔍 Testing handler discovery process...")
        
        handlers_config = config.get('handlers', {})
        use_discovery = handlers_config.get('use_discovery', False)
        
        if use_discovery:
            self.test_package_discovery(handlers_config.get('handler_packages', []))
        
        # Test explicit handler registration
        handler_configs = {
            k: v for k, v in handlers_config.items() 
            if k not in ['use_discovery', 'default_handler', 'handler_packages'] and isinstance(v, dict)
        }
        
        if handler_configs:
            self.test_explicit_handler_registration(handler_configs)
    
    def test_package_discovery(self, packages: List[str]):
        """Test package-based handler discovery."""
        logger.info("🔍 Testing package discovery...")
        
        if not packages:
            packages = ["a2a_server.tasks.handlers"]
            
        for package_name in packages:
            try:
                # Try to import the discovery module
                from a2a_server.tasks.discovery import discover_handlers_in_package
                
                handlers = list(discover_handlers_in_package(package_name))
                if handlers:
                    self.results.add_success(f"Discovered {len(handlers)} handlers in {package_name}")
                    for handler_class in handlers:
                        self.results.discovered_handlers.append(handler_class.__name__)
                        logger.info(f"  - {handler_class.__name__}")
                else:
                    self.results.add_warning(f"No handlers discovered in package {package_name}")
                    
            except ImportError as e:
                self.results.add_issue(f"Cannot import discovery module", str(e))
            except Exception as e:
                self.results.add_issue(f"Error during package discovery for {package_name}", str(e))
    
    def test_explicit_handler_registration(self, handler_configs: Dict[str, Any]):
        """Test explicit handler registration."""
        logger.info("🔍 Testing explicit handler registration...")
        
        for name, config in handler_configs.items():
            try:
                # Try to create the handler
                handler_type = config.get('type')
                if not handler_type:
                    continue
                    
                module_path, _, class_name = handler_type.rpartition('.')
                module = importlib.import_module(module_path)
                handler_class = getattr(module, class_name)
                
                # Check if we can create it
                sig = inspect.signature(handler_class.__init__)
                valid_params = set(sig.parameters.keys()) - {"self"}
                
                test_kwargs = {k: v for k, v in config.items() if k in valid_params}
                test_kwargs['name'] = name
                
                # For agent-based handlers, we need to handle the agent parameter
                if 'agent' in valid_params and config.get('agent'):
                    agent_spec = config['agent']
                    if isinstance(agent_spec, str):
                        try:
                            agent_module_path, _, agent_func_name = agent_spec.rpartition('.')
                            agent_module = importlib.import_module(agent_module_path)
                            agent_factory = getattr(agent_module, agent_func_name)
                            
                            if callable(agent_factory):
                                # Try to create agent with config
                                agent_config = {k: v for k, v in config.items() 
                                               if k not in ['type', 'name', 'agent', 'agent_card']}
                                test_kwargs['agent'] = agent_factory(**agent_config)
                                self.results.add_success(f"✅ Agent created for handler '{name}'")
                            else:
                                test_kwargs['agent'] = agent_factory
                                
                        except Exception as e:
                            self.results.add_issue(f"Failed to create agent for handler '{name}'", str(e))
                            continue
                
                # Try to create the handler
                handler = handler_class(**test_kwargs)
                self.results.add_success(f"✅ Handler '{name}' created successfully")
                
            except Exception as e:
                self.results.add_issue(f"Failed to create handler '{name}'", str(e))
                logger.exception(f"Error creating handler '{name}':")
    
    def simulate_startup(self, config: Dict[str, Any]):
        """Simulate the A2A server startup process."""
        logger.info("🔍 Simulating A2A server startup...")
        
        try:
            # Import required modules
            from a2a_server.tasks.task_manager import TaskManager
            from a2a_server.pubsub import EventBus
            
            # Create components
            event_bus = EventBus()
            task_manager = TaskManager(event_bus)
            
            self.results.add_success("✅ TaskManager and EventBus created")
            
            # Simulate handler registration
            handlers_config = config.get('handlers', {})
            use_discovery = handlers_config.get('use_discovery', False)
            
            if use_discovery:
                # Try discovery
                from a2a_server.tasks.discovery import register_discovered_handlers
                
                handler_packages = handlers_config.get('handler_packages', ["a2a_server.tasks.handlers"])
                
                register_discovered_handlers(
                    task_manager,
                    packages=handler_packages,
                    **{k: v for k, v in handlers_config.items() 
                       if k not in ['use_discovery', 'default_handler', 'handler_packages'] and isinstance(v, dict)}
                )
                
                # Check what was registered
                registered_handlers = list(task_manager._handlers.keys())
                default_handler = task_manager._default_handler
                
                if registered_handlers:
                    self.results.add_success(f"✅ Discovery registered handlers: {registered_handlers}")
                    if default_handler:
                        self.results.add_success(f"✅ Default handler set: {default_handler}")
                    else:
                        self.results.add_warning("No default handler set after discovery")
                else:
                    self.results.add_issue("Discovery failed to register any handlers")
                    
            else:
                # Explicit handler registration
                handler_configs = {
                    k: v for k, v in handlers_config.items() 
                    if k not in ['use_discovery', 'default_handler', 'handler_packages'] and isinstance(v, dict)
                }
                
                if handler_configs:
                    from a2a_server.tasks.discovery import register_discovered_handlers
                    
                    register_discovered_handlers(
                        task_manager,
                        packages=None,
                        **handler_configs
                    )
                    
                    registered_handlers = list(task_manager._handlers.keys())
                    default_handler = task_manager._default_handler
                    
                    if registered_handlers:
                        self.results.add_success(f"✅ Explicit registration succeeded: {registered_handlers}")
                        if default_handler:
                            self.results.add_success(f"✅ Default handler set: {default_handler}")
                        else:
                            self.results.add_warning("No default handler set after explicit registration")
                    else:
                        self.results.add_issue("Explicit registration failed to register any handlers")
                else:
                    self.results.add_issue("No handlers to register and use_discovery=false")
            
            # Test handler resolution
            try:
                default_handler_obj = task_manager._resolve_handler(None)
                self.results.add_success(f"✅ Default handler resolution works: {default_handler_obj.name}")
            except Exception as e:
                self.results.add_issue("Default handler resolution failed", str(e))
                
            try:
                default_handler_obj = task_manager._resolve_handler('default')
                self.results.add_success(f"✅ 'default' handler resolution works: {default_handler_obj.name}")
            except Exception as e:
                self.results.add_issue("'default' handler resolution failed", str(e))
                
        except Exception as e:
            self.results.add_issue("Failed to simulate startup", str(e))
            logger.exception("Startup simulation error:")
    
    def run_diagnostics(self) -> DiagnosticResults:
        """Run all diagnostics and return results."""
        logger.info("🏥 Starting A2A Server Diagnostics...")
        
        # Find and load config
        config_file = self.find_config_file()
        if not config_file:
            self.results.add_issue("No configuration file found", 
                                 "Looked for: agent.yaml, config.yaml, a2a_config.yaml")
            return self.results
        
        config = self.load_config(config_file)
        if not config:
            return self.results
        
        # Run diagnostics
        self.check_python_environment()
        
        if 'a2a_server' not in self.results.import_errors:
            self.analyze_handlers_config(config)
            self.test_discovery_process(config)
            self.simulate_startup(config)
        
        return self.results
    
    def print_report(self):
        """Print a comprehensive diagnostic report."""
        results = self.results
        
        print("\n" + "="*80)
        print("🏥 A2A SERVER DIAGNOSTIC REPORT")
        print("="*80)
        
        if results.issues:
            print(f"\n❌ CRITICAL ISSUES ({len(results.issues)}):")
            for i, issue in enumerate(results.issues, 1):
                print(f"  {i}. {issue['message']}")
                if issue['details']:
                    print(f"     Details: {issue['details']}")
        
        if results.warnings:
            print(f"\n⚠️  WARNINGS ({len(results.warnings)}):")
            for i, warning in enumerate(results.warnings, 1):
                print(f"  {i}. {warning['message']}")
                if warning['details']:
                    print(f"     Details: {warning['details']}")
        
        if results.successes:
            print(f"\n✅ SUCCESSFUL CHECKS ({len(results.successes)}):")
            for i, success in enumerate(results.successes, 1):
                print(f"  {i}. {success['message']}")
        
        if results.discovered_handlers:
            print(f"\n🔍 DISCOVERED HANDLERS:")
            for handler in results.discovered_handlers:
                print(f"  - {handler}")
        
        # Summary and recommendations
        print(f"\n📊 SUMMARY:")
        print(f"  Issues: {len(results.issues)}")
        print(f"  Warnings: {len(results.warnings)}")
        print(f"  Successes: {len(results.successes)}")
        
        if results.issues:
            print(f"\n🔧 RECOMMENDATIONS:")
            if any("No handlers" in issue['message'] for issue in results.issues):
                print("  1. Check your handler configuration in the YAML file")
                print("  2. Ensure handler classes can be imported")
                print("  3. Consider enabling use_discovery: true")
            
            if any("import" in issue['message'].lower() for issue in results.issues):
                print("  4. Check your Python environment and package installations")
                print("  5. Verify all required dependencies are installed")
        
        print("\n" + "="*80)

def main():
    """Main diagnostic function."""
    config_file = sys.argv[1] if len(sys.argv) > 1 else None
    
    diagnostic = A2ADiagnostic(config_file)
    diagnostic.run_diagnostics()
    diagnostic.print_report()
    
    # Exit with error code if there are critical issues
    if diagnostic.results.issues:
        sys.exit(1)
    else:
        print("\n🎉 No critical issues found!")
        sys.exit(0)

if __name__ == "__main__":
    main()