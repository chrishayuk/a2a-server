# a2a_server/tasks/discovery.py
"""
Fixed automatic discovery and registration of TaskHandler subclasses with comprehensive debugging.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
import sys
import types
import time
import traceback
import json
from typing import Iterator, List, Optional, Type, Dict, Any

from a2a_server.tasks.handlers.task_handler import TaskHandler

logger = logging.getLogger(__name__)

# Global tracking to prevent duplicate operations
_DISCOVERY_CALLS = []
_CREATED_AGENTS = {}
_REGISTERED_HANDLERS = set()

# ---------------------------------------------------------------------------
# Optional shim: guarantee that *something* called `pkg_resources` exists
# ---------------------------------------------------------------------------
try:
    import pkg_resources  # noqa: F401  (real module from setuptools)
except ModuleNotFoundError:  # pragma: no cover
    stub = types.ModuleType("pkg_resources")
    stub.iter_entry_points = lambda group: ()  # type: ignore[arg-type]
    sys.modules["pkg_resources"] = stub
    logger.debug("Created stub pkg_resources module (setuptools not installed)")


def _make_hashable(obj):
    """
    Convert any object to a hashable representation for caching purposes.
    
    Args:
        obj: Any object that needs to be made hashable
        
    Returns:
        A hashable representation of the object
    """
    if isinstance(obj, dict):
        return tuple(sorted((_make_hashable(k), _make_hashable(v)) for k, v in obj.items()))
    elif isinstance(obj, (list, tuple)):
        return tuple(_make_hashable(item) for item in obj)
    elif isinstance(obj, set):
        return tuple(sorted(_make_hashable(item) for item in obj))
    elif hasattr(obj, '__dict__'):
        # For objects with __dict__, use their string representation
        return str(obj)
    else:
        # For basic types (int, str, bool, None, etc.)
        try:
            hash(obj)  # Test if it's already hashable
            return obj
        except TypeError:
            # If not hashable, convert to string
            return str(obj)


def _create_agent_cache_key(agent_spec: str, agent_config: Dict[str, Any]) -> str:
    """
    Create a stable cache key for agent instances.
    
    Args:
        agent_spec: The agent specification string (module.function)
        agent_config: The configuration dictionary for the agent
        
    Returns:
        A stable cache key string
    """
    try:
        # Make the config hashable
        hashable_config = _make_hashable(agent_config)
        
        # Create a stable hash using JSON serialization as backup
        try:
            config_hash = hash(hashable_config)
        except TypeError:
            # Fallback: use JSON string hash (slower but more reliable)
            config_json = json.dumps(agent_config, sort_keys=True, default=str)
            config_hash = hash(config_json)
        
        return f"{agent_spec}#{config_hash}"
        
    except Exception as e:
        logger.warning(f"Failed to create stable cache key for agent {agent_spec}: {e}")
        # Emergency fallback: use timestamp to ensure uniqueness
        return f"{agent_spec}#{int(time.time() * 1000000)}"


def _validate_agent_configuration(
    handler_name: str, 
    is_agent_handler: bool, 
    agent_spec: Any, 
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Validate agent configuration for a handler.
    
    Returns:
        Dictionary with 'valid' (bool), 'agent_spec' (processed), and 'error' (str) keys
    """
    if is_agent_handler:
        if not agent_spec:
            return {
                'valid': False,
                'error': f"Agent-based handler '{handler_name}' missing 'agent' configuration",
                'agent_spec': None
            }
        
        # Validate agent_spec format
        if isinstance(agent_spec, str):
            # Should be a module.function_name format
            if '.' not in agent_spec:
                return {
                    'valid': False,
                    'error': f"Agent spec '{agent_spec}' should be in 'module.function' format",
                    'agent_spec': None
                }
            
            # Try to validate the module path exists
            try:
                module_path, _, func_name = agent_spec.rpartition('.')
                importlib.import_module(module_path)  # Just check if module exists
            except ImportError:
                return {
                    'valid': False,
                    'error': f"Cannot import agent module '{module_path}' for handler '{handler_name}'",
                    'agent_spec': None
                }
        
        elif not callable(agent_spec) and not hasattr(agent_spec, '__class__'):
            return {
                'valid': False,
                'error': f"Agent spec for '{handler_name}' must be a string path, callable, or object instance",
                'agent_spec': None
            }
        
        return {
            'valid': True,
            'agent_spec': agent_spec,
            'error': None
        }
    
    else:  # Not an agent handler
        if agent_spec:
            logger.debug(f"⚠️ Standalone handler '{handler_name}' has unnecessary 'agent' configuration - ignoring")
        
        return {
            'valid': True,
            'agent_spec': None,  # Clear agent_spec for non-agent handlers
            'error': None
        }


def _is_agent_based_handler(handler_class: Type[TaskHandler]) -> bool:
    """
    Precisely determine if a handler class requires an agent instance.
    
    This function uses multiple criteria to reliably detect agent-based handlers
    without false positives from naming patterns.
    """
    # Method 1: Check for explicit requires_agent attribute
    if hasattr(handler_class, 'requires_agent'):
        requires_agent = getattr(handler_class, 'requires_agent')
        if isinstance(requires_agent, bool):
            return requires_agent
        elif callable(requires_agent):
            try:
                return requires_agent()
            except Exception:
                pass
    
    # Method 2: Inspect constructor signature for 'agent' parameter
    try:
        sig = inspect.signature(handler_class.__init__)
        params = sig.parameters
        
        # Check if 'agent' is a required parameter (no default value)
        if 'agent' in params:
            agent_param = params['agent']
            # If agent parameter has no default, it's likely required
            if agent_param.default is inspect.Parameter.empty:
                return True
            # If it has a default of None, it might be optional
            elif agent_param.default is None:
                # Check if there are type hints that suggest it's expected
                if agent_param.annotation != inspect.Parameter.empty:
                    annotation_str = str(agent_param.annotation)
                    # Look for agent-related type hints
                    if any(keyword in annotation_str.lower() for keyword in ['agent', 'llm', 'model']):
                        return True
    except Exception as e:
        logger.debug(f"Could not inspect constructor signature for {handler_class.__name__}: {e}")
    
    # Method 3: Check inheritance hierarchy for known agent-based classes
    for base_class in inspect.getmro(handler_class):
        class_name = base_class.__name__
        module_name = getattr(base_class, '__module__', '')
        
        # Known agent-based handler base classes
        agent_base_classes = {
            'GoogleADKHandler',
            'ChukAgentHandler', 
            'LLMAgentHandler',
            'AgentTaskHandler'
        }
        
        if class_name in agent_base_classes:
            return True
        
        # Check for agent-related modules
        agent_modules = {
            'a2a_server.tasks.handlers.adk',
            'a2a_server.tasks.handlers.agent',
            'a2a_server.tasks.handlers.llm'
        }
        
        if any(module_name.startswith(agent_mod) for agent_mod in agent_modules):
            # Additional check: ensure it's not a base class itself
            if class_name.endswith('Handler') and 'Base' not in class_name and 'Abstract' not in class_name:
                return True
    
    # Method 4: Check for agent-related attributes in the class
    agent_attributes = [
        'agent', '_agent', 'llm_agent', 'adk_agent', 
        'model', '_model', 'client', '_client'
    ]
    
    for attr_name in agent_attributes:
        if hasattr(handler_class, attr_name):
            # Check if it's a class attribute (not inherited from object)
            if attr_name in handler_class.__dict__:
                return True
    
    # Method 5: Check for agent-related methods
    agent_methods = [
        'invoke_agent', 'call_agent', 'query_agent',
        'process_with_agent', '_create_agent', '_setup_agent'
    ]
    
    for method_name in agent_methods:
        if hasattr(handler_class, method_name):
            if method_name in handler_class.__dict__:
                return True
    
    # Method 6: Final fallback - strict name-based check with module verification
    class_name = handler_class.__name__
    module_name = getattr(handler_class, '__module__', '')
    
    # Only trust name-based detection if from known agent modules
    if any(module_name.startswith(agent_mod) for agent_mod in [
        'a2a_server.tasks.handlers.adk',
        'a2a_server.tasks.handlers.agent'
    ]):
        name_indicators = ['ADK', 'Agent', 'LLM', 'GPT', 'Claude']
        if any(indicator in class_name for indicator in name_indicators):
            # Exclude base/abstract classes
            if not any(exclusion in class_name for exclusion in ['Base', 'Abstract', 'Interface']):
                return True
    
    # Default: assume it's not agent-based
    return False


# ---------------------------------------------------------------------------#
# Package-based discovery                                                    #
# ---------------------------------------------------------------------------#
def discover_handlers_in_package(package_name: str) -> Iterator[Type[TaskHandler]]:
    """
    Yield every concrete ``TaskHandler`` subclass found inside *package_name*
    and its sub-packages.
    """
    try:
        package = importlib.import_module(package_name)
        logger.debug("Scanning package %s for handlers", package_name)
    except ImportError:
        logger.debug("Could not import package %s for handler discovery", package_name)
        return

    prefix = package.__name__ + "."
    scanned = 0

    for _, modname, _ in pkgutil.walk_packages(package.__path__, prefix):
        scanned += 1
        try:
            module = importlib.import_module(modname)
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(obj, TaskHandler)
                    and obj is not TaskHandler
                    and not getattr(obj, "abstract", False)
                    and not inspect.isabstract(obj)
                ):
                    logger.debug("Discovered handler %s in %s", obj.__name__, modname)
                    yield obj
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Error inspecting module %s: %s", modname, exc)

    logger.debug("Scanned %d modules in package %s", scanned, package_name)


# ---------------------------------------------------------------------------#
# Entry-point discovery                                                      #
# ---------------------------------------------------------------------------#
def _iter_entry_points() -> Iterator[types.SimpleNamespace]:
    """
    Unified helper that yields entry-points regardless of Python version /
    availability of importlib.metadata.
    """
    # Python ≥ 3.10 - importlib.metadata is in stdlib
    try:
        from importlib.metadata import entry_points

        yield from entry_points(group="a2a.task_handlers")
        return
    except Exception:  # pragma: no cover  pylint: disable=broad-except
        pass

    # Older Pythons - fall back to setuptools' pkg_resources
    try:
        import pkg_resources

        yield from pkg_resources.iter_entry_points(group="a2a.task_handlers")
    except Exception:  # pragma: no cover  pylint: disable=broad-except
        logger.debug("pkg_resources unavailable - skipping entry-point discovery")


def load_handlers_from_entry_points() -> Iterator[Type[TaskHandler]]:
    """
    Yield every concrete ``TaskHandler`` subclass advertised through the
    ``a2a.task_handlers`` entry-point group.
    """
    eps_scanned = 0
    handlers_found = 0

    for ep in _iter_entry_points():
        eps_scanned += 1
        try:
            cls = ep.load()  # type: ignore[attr-defined]
            if (
                inspect.isclass(cls)
                and issubclass(cls, TaskHandler)
                and cls is not TaskHandler
                and not getattr(cls, "abstract", False)
                and not inspect.isabstract(cls)
            ):
                handlers_found += 1
                logger.debug("Loaded handler %s from entry-point %s", cls.__name__, ep.name)
                yield cls
            else:
                logger.debug(
                    "Entry-point %s did not resolve to a concrete TaskHandler (got %r)",
                    ep.name,
                    cls,
                )
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Failed to load handler from entry-point %s: %s", ep.name, exc)

    logger.debug(
        "Checked %d entry-points in group 'a2a.task_handlers' - %d handlers loaded",
        eps_scanned,
        handlers_found,
    )


# ---------------------------------------------------------------------------#
# Public helpers                                                             #
# ---------------------------------------------------------------------------#
def discover_all_handlers(packages: Optional[List[str]] = None) -> List[Type[TaskHandler]]:
    """
    Discover all available handlers from *packages* **and** entry-points.
    """
    packages = packages or ["a2a_server.tasks.handlers"]
    logger.debug("Discovering handlers in packages: %s", packages)

    handlers: List[Type[TaskHandler]] = []

    for pkg in packages:
        found = list(discover_handlers_in_package(pkg))
        handlers.extend(found)
        logger.debug("Found %d handlers in package %s", len(found), pkg)

    ep_found = list(load_handlers_from_entry_points())
    handlers.extend(ep_found)
    logger.debug("Found %d handlers via entry-points", len(ep_found))

    logger.debug("Discovered %d task handlers in total", len(handlers))
    return handlers


def register_discovered_handlers(
    task_manager,
    packages: Optional[List[str]] = None,
    default_handler_class: Optional[Type[TaskHandler]] = None,
    extra_kwargs: Optional[Dict[str, Any]] = None,
    **explicit_handlers
) -> None:
    """
    Enhanced handler registration with comprehensive configuration support and duplicate prevention.
    
    Args:
        task_manager: The task manager to register handlers with
        packages: List of packages to scan for handlers
        default_handler_class: Optional specific class to use as default
        extra_kwargs: Additional keyword arguments to pass to handler constructors
        **explicit_handlers: Explicit handler configurations from YAML
    """
    call_time = time.time()
    call_id = f"discovery-{int(call_time * 1000) % 10000}"
    
    # Track this discovery call
    global _DISCOVERY_CALLS
    _DISCOVERY_CALLS.append({
        'id': call_id,
        'time': call_time,
        'packages': packages,
        'explicit_handlers': list(explicit_handlers.keys()) if explicit_handlers else []
    })
    
    # Check for duplicate discovery calls
    recent_calls = [call for call in _DISCOVERY_CALLS if call_time - call['time'] < 10]
    if len(recent_calls) > 1:
        logger.error(f"❌ DUPLICATE DISCOVERY CALL DETECTED!")
        logger.error(f"   Current call: {call_id}")
        logger.error(f"   Recent calls: {[call['id'] for call in recent_calls[:-1]]}")
        logger.error(f"   This suggests register_discovered_handlers is being called multiple times!")
        
        # Log call stack for debugging
        stack = traceback.extract_stack()
        caller_info = "unknown"
        if len(stack) >= 2:
            caller_frame = stack[-2]
            caller_info = f"{caller_frame.filename}:{caller_frame.lineno} in {caller_frame.name}"
        logger.error(f"   Called from: {caller_info}")
    
    logger.debug(f"🔧 DISCOVERY CALL {call_id}: Starting handler registration")
    logger.debug(f"   Packages: {packages}")
    logger.debug(f"   Explicit handlers: {list(explicit_handlers.keys()) if explicit_handlers else 'None'}")
    
    extra_kwargs = extra_kwargs or {}
    
    # Register explicit handlers from configuration first
    if explicit_handlers:
        logger.debug(f"🔧 Registering {len(explicit_handlers)} explicit handlers from configuration")
        _register_explicit_handlers(task_manager, explicit_handlers, default_handler_class, call_id)
    
    # Only do package discovery if explicitly requested
    if packages:
        logger.debug(f"🔧 Starting package discovery for {call_id}")
        handlers = discover_all_handlers(packages)
        if not handlers:
            logger.debug("No task handlers discovered from packages")
            return

        registered = 0
        default_name = None
        other_names: list[str] = []

        for cls in handlers:
            # Skip if this handler was already registered explicitly
            handler_name = getattr(cls, '_name', cls.__name__.lower().replace('handler', ''))
            
            # Check if this handler name was already processed
            if handler_name in _REGISTERED_HANDLERS:
                logger.debug(f"⚠️ Skipping {cls.__name__} - handler '{handler_name}' already registered globally")
                continue
                
            if explicit_handlers and handler_name in explicit_handlers:
                logger.debug(f"Skipping {cls.__name__} - already registered explicitly")
                continue
                
            try:
                # Get the constructor signature to see what parameters it accepts
                sig = inspect.signature(cls.__init__)
                valid_params = set(sig.parameters.keys()) - {"self"}
                
                # Filter extra_kwargs to only include parameters the constructor accepts
                filtered_kwargs = {k: v for k, v in extra_kwargs.items() if k in valid_params}
                
                if filtered_kwargs:
                    logger.debug("Passing %s to %s constructor", filtered_kwargs.keys(), cls.__name__)
                
                handler = cls(**filtered_kwargs)
                is_default = (
                    (default_handler_class is not None and cls is default_handler_class)
                    or (default_handler_class is None and not default_name and not explicit_handlers)
                )
                
                # Track that this handler name has been registered
                _REGISTERED_HANDLERS.add(handler_name)
                
                task_manager.register_handler(handler, default=is_default)
                registered += 1
                if is_default:
                    default_name = handler.name
                else:
                    other_names.append(handler.name)
                    
            except Exception as exc:
                logger.error("Failed to instantiate handler %s: %s", cls.__name__, exc)

        if registered:
            if default_name:
                logger.debug(
                    "Registered %d discovered task handlers (default: %s%s)",
                    registered,
                    default_name,
                    f', others: {", ".join(other_names)}' if other_names else "",
                )
            else:
                logger.debug("Registered %d discovered task handlers: %s", registered, ", ".join(other_names))
    
    logger.debug(f"✅ DISCOVERY CALL {call_id}: Completed")


def _register_explicit_handlers(
    task_manager, 
    explicit_handlers: Dict[str, Dict[str, Any]], 
    default_handler_class: Optional[Type[TaskHandler]] = None,
    discovery_call_id: str = "unknown"
) -> None:
    """
    Register handlers explicitly defined in configuration with comprehensive debugging and duplicate prevention.
    """
    default_handler_name = None
    registered_names = []
    
    logger.debug(f"🔧 [{discovery_call_id}] Processing {len(explicit_handlers)} explicit handlers")
    
    for handler_name, config in explicit_handlers.items():
        if not isinstance(config, dict):
            logger.debug(f"⚠️ Skipping handler '{handler_name}' - config is not a dict: {type(config)}")
            continue
            
        # Check if this handler was already registered
        if handler_name in _REGISTERED_HANDLERS:
            logger.error(f"❌ Handler '{handler_name}' already registered - skipping to prevent duplicates")
            continue
            
        logger.debug(f"🎯 [{discovery_call_id}] Processing handler: {handler_name}")
        logger.debug(f"🔧 Config keys: {list(config.keys())}")
        
        try:
            # Extract handler type (class path)
            handler_type = config.get('type')
            if not handler_type:
                logger.error(f"❌ Handler '{handler_name}' missing 'type' configuration")
                continue
            
            # Import handler class
            try:
                module_path, _, class_name = handler_type.rpartition('.')
                module = importlib.import_module(module_path)
                handler_class = getattr(module, class_name)
                logger.debug(f"✅ Imported handler class: {handler_class.__name__}")
            except (ImportError, AttributeError) as e:
                logger.error(f"❌ Failed to import handler class '{handler_type}': {e}")
                continue
            
            # Check if this is an agent-based handler using precise criteria
            is_agent_handler = _is_agent_based_handler(handler_class)
            
            logger.debug(f"🔍 Handler type analysis: {class_name}, is_agent_handler: {is_agent_handler}")
            
            # Extract agent specification with validation
            agent_spec = config.get('agent')
            agent_validation = _validate_agent_configuration(handler_name, is_agent_handler, agent_spec, config)
            
            if not agent_validation['valid']:
                logger.error(f"❌ {agent_validation['error']}")
                continue
                
            agent_spec = agent_validation['agent_spec']
            
            # Prepare constructor arguments
            handler_kwargs = config.copy()
            handler_kwargs.pop('type', None)  # Remove meta fields
            handler_kwargs.pop('agent_card', None)
            
            # Set the name explicitly
            handler_kwargs['name'] = handler_name
            
            # Debug constructor parameters
            sig = inspect.signature(handler_class.__init__)
            valid_params = set(sig.parameters.keys()) - {"self"}
            logger.debug(f"🔧 Handler constructor accepts: {sorted(valid_params)}")
            
            # Process agent for agent-based handlers with comprehensive debugging and caching
            if is_agent_handler and agent_spec:
                logger.debug(f"🏭 [{discovery_call_id}] Processing agent for {handler_name}: {agent_spec}")
                
                if isinstance(agent_spec, str):
                    try:
                        # Extract agent configuration parameters
                        agent_config = {k: v for k, v in config.items() 
                                       if k not in ['type', 'name', 'agent', 'agent_card']}
                        
                        logger.debug(f"🔧 Agent config parameters: {list(agent_config.keys())}")
                        logger.debug(f"🔧 Agent config values: {agent_config}")
                        
                        # Special logging for enable_sessions
                        if 'enable_sessions' in agent_config:
                            logger.debug(f"🔑 enable_sessions found in config: {agent_config['enable_sessions']} (type: {type(agent_config['enable_sessions'])})")
                        else:
                            logger.debug(f"⚠️ enable_sessions NOT found in agent config for {handler_name}")
                        
                        # Create a unique key for this agent configuration using the fixed function
                        agent_key = _create_agent_cache_key(agent_spec, agent_config)
                        
                        # Check if we've already created this exact agent
                        global _CREATED_AGENTS
                        if agent_key in _CREATED_AGENTS:
                            logger.debug(f"🔄 [{discovery_call_id}] Reusing cached agent for {handler_name}")
                            logger.debug(f"   Agent key: {agent_key}")
                            logger.debug(f"   Original creation: {_CREATED_AGENTS[agent_key]['creation_info']}")
                            handler_kwargs['agent'] = _CREATED_AGENTS[agent_key]['instance']
                        else:
                            # Import and create the agent
                            logger.debug(f"🏭 [{discovery_call_id}] Creating NEW agent from factory: {agent_spec}")
                            
                            agent_module_path, _, agent_func_name = agent_spec.rpartition('.')
                            agent_module = importlib.import_module(agent_module_path)
                            agent_factory = getattr(agent_module, agent_func_name)
                            
                            if callable(agent_factory):
                                logger.debug(f"✅ Agent factory is callable: {agent_func_name}")
                                logger.debug(f"🎯 Calling factory with {len(agent_config)} parameters: {list(agent_config.keys())}")
                                
                                # Get caller information for debugging
                                stack = traceback.extract_stack()
                                caller_info = "unknown"
                                if len(stack) >= 3:
                                    caller_frame = stack[-3]
                                    caller_info = f"{caller_frame.filename}:{caller_frame.lineno}"
                                
                                try:
                                    # Add debug wrapper around agent factory call
                                    logger.debug(f"🔧 [{discovery_call_id}] About to call agent factory: {agent_func_name}")
                                    logger.debug(f"   Parameters: {agent_config}")
                                    
                                    agent_instance = agent_factory(**agent_config)
                                    
                                    logger.debug(f"✅ [{discovery_call_id}] Agent instance created successfully: {type(agent_instance)}")
                                    
                                    # Cache the created agent with creation info
                                    _CREATED_AGENTS[agent_key] = {
                                        'instance': agent_instance,
                                        'creation_info': {
                                            'handler_name': handler_name,
                                            'discovery_call': discovery_call_id,
                                            'caller': caller_info,
                                            'time': time.time()
                                        }
                                    }
                                    
                                    handler_kwargs['agent'] = agent_instance
                                    
                                    # Verification: Check if enable_sessions was applied correctly
                                    if hasattr(agent_instance, 'enable_sessions'):
                                        expected_sessions = agent_config.get('enable_sessions', False)
                                        actual_sessions = agent_instance.enable_sessions
                                        
                                        logger.debug(f"🔍 Session verification for {handler_name}:")
                                        logger.debug(f"   Expected enable_sessions: {expected_sessions}")
                                        logger.debug(f"   Actual enable_sessions: {actual_sessions}")
                                        
                                        if actual_sessions == expected_sessions:
                                            logger.debug(f"✅ Session configuration CORRECT for {handler_name}")
                                        else:
                                            logger.error(f"❌ Session configuration MISMATCH for {handler_name}!")
                                            logger.error(f"   This indicates the agent factory is not using the enable_sessions parameter correctly")
                                    else:
                                        logger.debug(f"⚠️ Agent {handler_name} has no 'enable_sessions' attribute")
                                        
                                except Exception as factory_error:
                                    logger.error(f"❌ Agent factory call failed for {handler_name}")
                                    logger.error(f"   Factory: {agent_spec}")
                                    logger.error(f"   Parameters: {agent_config}")
                                    logger.error(f"   Error: {factory_error}")
                                    logger.exception("Full agent factory error:")
                                    continue
                                    
                            else:
                                # Direct agent instance (not a factory function)
                                logger.debug(f"🔧 Agent spec is not callable, using directly: {type(agent_factory)}")
                                
                                # Still cache it to prevent issues
                                _CREATED_AGENTS[agent_key] = {
                                    'instance': agent_factory,
                                    'creation_info': {
                                        'handler_name': handler_name,
                                        'discovery_call': discovery_call_id,
                                        'direct_instance': True,
                                        'time': time.time()
                                    }
                                }
                                handler_kwargs['agent'] = agent_factory
                        
                    except Exception as e:
                        logger.error(f"❌ Failed to process agent from factory '{agent_spec}': {e}")
                        logger.exception("Agent processing error:")
                        continue
                else:
                    # Direct agent specification (not a string path)
                    logger.debug(f"🔧 Using direct agent specification: {type(agent_spec)}")
                    handler_kwargs['agent'] = agent_spec
            
            # Filter to valid parameters only
            filtered_kwargs = {k: v for k, v in handler_kwargs.items() if k in valid_params}
            
            logger.debug(f"🔧 Final handler kwargs: {list(filtered_kwargs.keys())}")
            logger.debug(f"🔧 Filtered out: {set(handler_kwargs.keys()) - set(filtered_kwargs.keys())}")
            
            # Log handler type for debugging
            if is_agent_handler:
                logger.debug(f"🤖 [{discovery_call_id}] Registering agent-based handler: {handler_name}")
            else:
                logger.debug(f"⚙️ [{discovery_call_id}] Registering standalone handler: {handler_name}")
            
            # Instantiate handler with comprehensive error handling
            try:
                logger.debug(f"🏗️ [{discovery_call_id}] Creating handler instance: {class_name}")
                handler = handler_class(**filtered_kwargs)
                logger.debug(f"✅ [{discovery_call_id}] Handler instance created successfully: {handler_name}")
            except Exception as handler_error:
                logger.error(f"❌ Handler instantiation failed for {handler_name}")
                logger.error(f"   Class: {handler_class}")
                logger.error(f"   Args: {filtered_kwargs}")
                logger.error(f"   Error: {handler_error}")
                logger.exception("Full handler instantiation error:")
                continue
            
            # Determine if this should be default
            is_default = (
                config.get('default', False) or
                (default_handler_class is not None and handler_class is default_handler_class) or
                (not default_handler_name and not registered_names)
            )
            
            # Register with task manager
            try:
                # Track that this handler name has been registered
                _REGISTERED_HANDLERS.add(handler_name)
                
                task_manager.register_handler(handler, default=is_default)
                registered_names.append(handler_name)
                
                if is_default:
                    default_handler_name = handler_name
                    
                logger.debug(f"✅ [{discovery_call_id}] Successfully registered handler '{handler_name}'{' (default)' if is_default else ''}")
                
                # Final verification: If this was an agent-based handler with sessions, verify one more time
                if is_agent_handler and hasattr(handler, 'agent') and hasattr(handler.agent, 'enable_sessions'):
                    final_sessions = handler.agent.enable_sessions
                    config_sessions = config.get('enable_sessions', False)
                    logger.debug(f"🏁 FINAL CHECK for {handler_name}: config={config_sessions}, agent={final_sessions}")
                    
            except Exception as registration_error:
                logger.error(f"❌ Handler registration failed for {handler_name}: {registration_error}")
                logger.exception("Handler registration error:")
                # Remove from registered set if registration failed
                _REGISTERED_HANDLERS.discard(handler_name)
                continue
                
        except Exception as exc:
            logger.error(f"❌ Unexpected error processing handler '{handler_name}': {exc}")
            logger.exception("Unexpected handler processing error:")
    
    # Final summary
    if registered_names:
        logger.debug(f"🎉 [{discovery_call_id}] Successfully registered {len(registered_names)} handlers: {', '.join(registered_names)}")
        if default_handler_name:
            logger.debug(f"🏆 [{discovery_call_id}] Default handler: {default_handler_name}")
    else:
        logger.debug(f"⚠️ [{discovery_call_id}] No handlers were successfully registered from configuration")

    # Clean up old discovery calls to prevent memory leak
    current_time = time.time()
    _DISCOVERY_CALLS[:] = [call for call in _DISCOVERY_CALLS if current_time - call['time'] < 300]  # Keep 5 minutes


def get_discovery_stats() -> Dict[str, Any]:
    """Get statistics about discovery calls and agent creation."""
    return {
        "discovery_calls": len(_DISCOVERY_CALLS),
        "created_agents": len(_CREATED_AGENTS),
        "registered_handlers": len(_REGISTERED_HANDLERS),
        "recent_discovery_calls": [
            {
                'id': call['id'],
                'time': call['time'],
                'handlers': call['explicit_handlers']
            }
            for call in _DISCOVERY_CALLS
        ],
        "agent_cache": {
            key: {
                'handler_name': info['creation_info'].get('handler_name'),
                'discovery_call': info['creation_info'].get('discovery_call'),
                'time': info['creation_info'].get('time')
            }
            for key, info in _CREATED_AGENTS.items()
        },
        "registered_handler_names": list(_REGISTERED_HANDLERS)
    }


__all__ = [
    "discover_handlers_in_package",
    "load_handlers_from_entry_points", 
    "discover_all_handlers",
    "register_discovered_handlers",
    "get_discovery_stats"
]