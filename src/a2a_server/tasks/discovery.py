# a2a_server/tasks/discovery.py
"""
automatic discovery and registration of TaskHandler subclasses with memory management.
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
import asyncio
import weakref
from typing import Iterator, List, Optional, Type, Dict, Any

from a2a_server.tasks.handlers.task_handler import TaskHandler

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# MEMORY-MANAGED GLOBALS with automatic cleanup
# ─────────────────────────────────────────────────────────────────────────────

class ManagedCache:
    """Memory-managed cache with automatic cleanup."""
    
    def __init__(self, max_size: int = 1000, cleanup_interval: int = 300):
        self.max_size = max_size
        self.cleanup_interval = cleanup_interval
        self._data: Dict[str, Dict[str, Any]] = {}
        self._access_times: Dict[str, float] = {}
        self._last_cleanup = time.time()
        
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get item from cache and update access time."""
        if key in self._data:
            self._access_times[key] = time.time()
            return self._data[key]
        return None
    
    def set(self, key: str, value: Dict[str, Any]) -> None:
        """Set item in cache with automatic cleanup."""
        current_time = time.time()
        self._data[key] = value
        self._access_times[key] = current_time
        
        # Trigger cleanup if needed
        if (current_time - self._last_cleanup > self.cleanup_interval or 
            len(self._data) > self.max_size):
            self._cleanup()
    
    def _cleanup(self) -> None:
        """Remove old entries to prevent memory growth."""
        current_time = time.time()
        self._last_cleanup = current_time
        
        # Remove entries older than 1 hour
        old_keys = [
            key for key, access_time in self._access_times.items()
            if current_time - access_time > 3600
        ]
        
        # If still too many, remove oldest entries
        if len(self._data) - len(old_keys) > self.max_size:
            # Sort by access time and remove oldest
            sorted_keys = sorted(
                self._access_times.items(), 
                key=lambda x: x[1]
            )
            additional_removals = len(self._data) - len(old_keys) - self.max_size + 100
            old_keys.extend([key for key, _ in sorted_keys[:additional_removals]])
        
        # Remove the entries
        for key in old_keys:
            self._data.pop(key, None)
            self._access_times.pop(key, None)
        
        if old_keys:
            logger.debug(f"Cleaned up {len(old_keys)} cache entries")
    
    def clear(self) -> None:
        """Clear all cache entries."""
        self._data.clear()
        self._access_times.clear()
        self._last_cleanup = time.time()
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": len(self._data),
            "max_size": self.max_size,
            "oldest_entry": min(self._access_times.values()) if self._access_times else None,
            "newest_entry": max(self._access_times.values()) if self._access_times else None,
            "last_cleanup": self._last_cleanup
        }

# Memory-managed global caches
_discovery_calls = ManagedCache(max_size=100, cleanup_interval=300)
_created_agents = ManagedCache(max_size=500, cleanup_interval=600)
_registered_handlers: set = set()

# Background cleanup task
_cleanup_task: Optional[asyncio.Task] = None

async def _background_cleanup():
    """Background task for periodic cleanup."""
    while True:
        try:
            await asyncio.sleep(300)  # Run every 5 minutes
            
            # Clean up caches
            _discovery_calls._cleanup()
            _created_agents._cleanup()
            
            # Clean up registered handlers set if it gets too large
            if len(_registered_handlers) > 1000:
                logger.warning("Registered handlers set very large, clearing for memory")
                _registered_handlers.clear()
                
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Background cleanup error: {e}")

def _ensure_cleanup_task():
    """Ensure background cleanup task is running."""
    global _cleanup_task
    if _cleanup_task is None or _cleanup_task.done():
        try:
            loop = asyncio.get_running_loop()
            _cleanup_task = loop.create_task(_background_cleanup())
        except RuntimeError:
            # No event loop running, cleanup will happen manually
            pass

# ─────────────────────────────────────────────────────────────────────────────
# EXISTING DISCOVERY CODE (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

# Optional shim: guarantee that *something* called `pkg_resources` exists
try:
    import pkg_resources  # noqa: F401  (real module from setuptools)
except ModuleNotFoundError:  # pragma: no cover
    stub = types.ModuleType("pkg_resources")
    stub.iter_entry_points = lambda group: ()  # type: ignore[arg-type]
    sys.modules["pkg_resources"] = stub
    logger.debug("Created stub pkg_resources module (setuptools not installed)")

def _make_hashable(obj):
    """Convert any object to a hashable representation for caching purposes."""
    if isinstance(obj, dict):
        return tuple(sorted((_make_hashable(k), _make_hashable(v)) for k, v in obj.items()))
    elif isinstance(obj, (list, tuple)):
        return tuple(_make_hashable(item) for item in obj)
    elif isinstance(obj, set):
        return tuple(sorted(_make_hashable(item) for item in obj))
    elif hasattr(obj, '__dict__'):
        return str(obj)
    else:
        try:
            hash(obj)
            return obj
        except TypeError:
            return str(obj)

def _create_agent_cache_key(agent_spec: str, agent_config: Dict[str, Any]) -> str:
    """Create a stable cache key for agent instances."""
    try:
        hashable_config = _make_hashable(agent_config)
        try:
            config_hash = hash(hashable_config)
        except TypeError:
            config_json = json.dumps(agent_config, sort_keys=True, default=str)
            config_hash = hash(config_json)
        return f"{agent_spec}#{config_hash}"
    except Exception as e:
        logger.warning(f"Failed to create stable cache key for agent {agent_spec}: {e}")
        return f"{agent_spec}#{int(time.time() * 1000000)}"

def _validate_agent_configuration(
    handler_name: str, 
    is_agent_handler: bool, 
    agent_spec: Any, 
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """Validate agent configuration for a handler."""
    if is_agent_handler:
        if not agent_spec:
            return {
                'valid': False,
                'error': f"Agent-based handler '{handler_name}' missing 'agent' configuration",
                'agent_spec': None
            }
        
        if isinstance(agent_spec, str):
            if '.' not in agent_spec:
                return {
                    'valid': False,
                    'error': f"Agent spec '{agent_spec}' should be in 'module.function' format",
                    'agent_spec': None
                }
            
            try:
                module_path, _, func_name = agent_spec.rpartition('.')
                importlib.import_module(module_path)
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
        
        return {'valid': True, 'agent_spec': agent_spec, 'error': None}
    
    else:
        if agent_spec:
            logger.debug(f"⚠️ Standalone handler '{handler_name}' has unnecessary 'agent' configuration - ignoring")
        return {'valid': True, 'agent_spec': None, 'error': None}

def _is_agent_based_handler(handler_class: Type[TaskHandler]) -> bool:
    """Determine if a handler class requires an agent instance."""
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
        
        if 'agent' in params:
            agent_param = params['agent']
            if agent_param.default is inspect.Parameter.empty:
                return True
            elif agent_param.default is None:
                if agent_param.annotation != inspect.Parameter.empty:
                    annotation_str = str(agent_param.annotation)
                    if any(keyword in annotation_str.lower() for keyword in ['agent', 'llm', 'model']):
                        return True
    except Exception as e:
        logger.debug(f"Could not inspect constructor signature for {handler_class.__name__}: {e}")
    
    # Method 3: Check inheritance hierarchy
    for base_class in inspect.getmro(handler_class):
        class_name = base_class.__name__
        module_name = getattr(base_class, '__module__', '')
        
        agent_base_classes = {
            'GoogleADKHandler',
            'ChukAgentHandler', 
            'LLMAgentHandler',
            'AgentTaskHandler'
        }
        
        if class_name in agent_base_classes:
            return True
        
        agent_modules = {
            'a2a_server.tasks.handlers.adk',
            'a2a_server.tasks.handlers.agent',
            'a2a_server.tasks.handlers.llm'
        }
        
        if any(module_name.startswith(agent_mod) for agent_mod in agent_modules):
            if class_name.endswith('Handler') and 'Base' not in class_name and 'Abstract' not in class_name:
                return True
    
    # Method 4: Check for agent-related attributes
    agent_attributes = [
        'agent', '_agent', 'llm_agent', 'adk_agent', 
        'model', '_model', 'client', '_client'
    ]
    
    for attr_name in agent_attributes:
        if hasattr(handler_class, attr_name):
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
    
    # Method 6: Name-based check with module verification
    class_name = handler_class.__name__
    module_name = getattr(handler_class, '__module__', '')
    
    if any(module_name.startswith(agent_mod) for agent_mod in [
        'a2a_server.tasks.handlers.adk',
        'a2a_server.tasks.handlers.agent'
    ]):
        name_indicators = ['ADK', 'Agent', 'LLM', 'GPT', 'Claude']
        if any(indicator in class_name for indicator in name_indicators):
            if not any(exclusion in class_name for exclusion in ['Base', 'Abstract', 'Interface']):
                return True
    
    return False

# ─────────────────────────────────────────────────────────────────────────────
# PACKAGE-BASED DISCOVERY (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

def discover_handlers_in_package(package_name: str) -> Iterator[Type[TaskHandler]]:
    """Yield every concrete TaskHandler subclass found inside package_name."""
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
        except Exception as exc:
            logger.debug("Error inspecting module %s: %s", modname, exc)

    logger.debug("Scanned %d modules in package %s", scanned, package_name)

def _iter_entry_points() -> Iterator[types.SimpleNamespace]:
    """Unified helper that yields entry-points regardless of Python version."""
    try:
        from importlib.metadata import entry_points
        yield from entry_points(group="a2a.task_handlers")
        return
    except Exception:
        pass

    try:
        import pkg_resources
        yield from pkg_resources.iter_entry_points(group="a2a.task_handlers")
    except Exception:
        logger.debug("pkg_resources unavailable - skipping entry-point discovery")

def load_handlers_from_entry_points() -> Iterator[Type[TaskHandler]]:
    """Yield every concrete TaskHandler subclass advertised through entry-points."""
    eps_scanned = 0
    handlers_found = 0

    for ep in _iter_entry_points():
        eps_scanned += 1
        try:
            cls = ep.load()
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
                logger.debug("Entry-point %s did not resolve to a concrete TaskHandler", ep.name)
        except Exception as exc:
            logger.debug("Failed to load handler from entry-point %s: %s", ep.name, exc)

    logger.debug("Checked %d entry-points - %d handlers loaded", eps_scanned, handlers_found)

def discover_all_handlers(packages: Optional[List[str]] = None) -> List[Type[TaskHandler]]:
    """Discover all available handlers from packages and entry-points."""
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

# ─────────────────────────────────────────────────────────────────────────────
# OPTIMIZED HANDLER REGISTRATION with memory management
# ─────────────────────────────────────────────────────────────────────────────

def register_discovered_handlers(
    task_manager,
    packages: Optional[List[str]] = None,
    default_handler_class: Optional[Type[TaskHandler]] = None,
    extra_kwargs: Optional[Dict[str, Any]] = None,
    **explicit_handlers
) -> None:
    """Enhanced handler registration with memory management."""
    
    # Ensure cleanup task is running
    _ensure_cleanup_task()
    
    call_time = time.time()
    call_id = f"discovery-{int(call_time * 1000) % 10000}"
    
    # Track this discovery call with managed cache
    call_data = {
        'id': call_id,
        'time': call_time,
        'packages': packages,
        'explicit_handlers': list(explicit_handlers.keys()) if explicit_handlers else []
    }
    _discovery_calls.set(call_id, call_data)
    
    # Check for recent duplicate calls
    recent_calls = []
    for key, data in _discovery_calls._data.items():
        if call_time - data['time'] < 10:
            recent_calls.append(data)
    
    if len(recent_calls) > 1:
        logger.error(f"❌ DUPLICATE DISCOVERY CALL DETECTED!")
        logger.error(f"   Current call: {call_id}")
        logger.error(f"   Recent calls: {[call['id'] for call in recent_calls[:-1]]}")
    
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
            handler_name = getattr(cls, '_name', cls.__name__.lower().replace('handler', ''))
            
            if handler_name in _registered_handlers:
                logger.debug(f"⚠️ Skipping {cls.__name__} - handler '{handler_name}' already registered")
                continue
                
            if explicit_handlers and handler_name in explicit_handlers:
                logger.debug(f"Skipping {cls.__name__} - already registered explicitly")
                continue
                
            try:
                sig = inspect.signature(cls.__init__)
                valid_params = set(sig.parameters.keys()) - {"self"}
                filtered_kwargs = {k: v for k, v in extra_kwargs.items() if k in valid_params}
                
                if filtered_kwargs:
                    logger.debug("Passing %s to %s constructor", filtered_kwargs.keys(), cls.__name__)
                
                handler = cls(**filtered_kwargs)
                is_default = (
                    (default_handler_class is not None and cls is default_handler_class)
                    or (default_handler_class is None and not default_name and not explicit_handlers)
                )
                
                _registered_handlers.add(handler_name)
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
                logger.debug("Registered %d discovered task handlers (default: %s%s)",
                           registered, default_name,
                           f', others: {", ".join(other_names)}' if other_names else "")
            else:
                logger.debug("Registered %d discovered task handlers: %s", 
                           registered, ", ".join(other_names))
    
    logger.debug(f"✅ DISCOVERY CALL {call_id}: Completed")

def _register_explicit_handlers(
    task_manager, 
    explicit_handlers: Dict[str, Dict[str, Any]], 
    default_handler_class: Optional[Type[TaskHandler]] = None,
    discovery_call_id: str = "unknown"
) -> None:
    """Register handlers with optimized agent caching."""
    default_handler_name = None
    registered_names = []
    
    logger.debug(f"🔧 [{discovery_call_id}] Processing {len(explicit_handlers)} explicit handlers")
    
    for handler_name, config in explicit_handlers.items():
        if not isinstance(config, dict):
            logger.debug(f"⚠️ Skipping handler '{handler_name}' - config is not a dict")
            continue
            
        if handler_name in _registered_handlers:
            logger.error(f"❌ Handler '{handler_name}' already registered - skipping to prevent duplicates")
            continue
            
        logger.debug(f"🎯 [{discovery_call_id}] Processing handler: {handler_name}")
        
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
            
            # Check if this is an agent-based handler
            is_agent_handler = _is_agent_based_handler(handler_class)
            
            # Extract agent specification with validation
            agent_spec = config.get('agent')
            agent_validation = _validate_agent_configuration(handler_name, is_agent_handler, agent_spec, config)
            
            if not agent_validation['valid']:
                logger.error(f"❌ {agent_validation['error']}")
                continue
                
            agent_spec = agent_validation['agent_spec']
            
            # Prepare constructor arguments
            handler_kwargs = config.copy()
            handler_kwargs.pop('type', None)
            handler_kwargs.pop('agent_card', None)
            handler_kwargs['name'] = handler_name
            
            # Debug constructor parameters
            sig = inspect.signature(handler_class.__init__)
            valid_params = set(sig.parameters.keys()) - {"self"}
            
            # Process agent for agent-based handlers with caching
            if is_agent_handler and agent_spec:
                logger.debug(f"🏭 [{discovery_call_id}] Processing agent for {handler_name}: {agent_spec}")
                
                if isinstance(agent_spec, str):
                    try:
                        # Extract agent configuration parameters
                        agent_config = {k: v for k, v in config.items() 
                                       if k not in ['type', 'name', 'agent', 'agent_card']}
                        
                        # Create unique cache key
                        agent_key = _create_agent_cache_key(agent_spec, agent_config)
                        
                        # Check cache first
                        cached_agent_data = _created_agents.get(agent_key)
                        if cached_agent_data:
                            logger.debug(f"🔄 [{discovery_call_id}] Reusing cached agent for {handler_name}")
                            handler_kwargs['agent'] = cached_agent_data['instance']
                        else:
                            # Create new agent
                            logger.debug(f"🏭 [{discovery_call_id}] Creating NEW agent from factory: {agent_spec}")
                            
                            agent_module_path, _, agent_func_name = agent_spec.rpartition('.')
                            agent_module = importlib.import_module(agent_module_path)
                            agent_factory = getattr(agent_module, agent_func_name)
                            
                            if callable(agent_factory):
                                try:
                                    agent_instance = agent_factory(**agent_config)
                                    
                                    # Cache the created agent with weak reference if possible
                                    try:
                                        weak_ref = weakref.ref(agent_instance)
                                        cache_entry = {
                                            'instance': agent_instance,
                                            'weak_ref': weak_ref,
                                            'creation_info': {
                                                'handler_name': handler_name,
                                                'discovery_call': discovery_call_id,
                                                'time': time.time()
                                            }
                                        }
                                    except TypeError:
                                        # Object doesn't support weak references
                                        cache_entry = {
                                            'instance': agent_instance,
                                            'creation_info': {
                                                'handler_name': handler_name,
                                                'discovery_call': discovery_call_id,
                                                'time': time.time()
                                            }
                                        }
                                    
                                    _created_agents.set(agent_key, cache_entry)
                                    handler_kwargs['agent'] = agent_instance
                                    
                                    # Verification
                                    if hasattr(agent_instance, 'enable_sessions'):
                                        expected_sessions = agent_config.get('enable_sessions', False)
                                        actual_sessions = agent_instance.enable_sessions
                                        
                                        if actual_sessions == expected_sessions:
                                            logger.debug(f"✅ Session configuration correct for {handler_name}")
                                        else:
                                            logger.error(f"❌ Session configuration mismatch for {handler_name}!")
                                    
                                except Exception as factory_error:
                                    logger.error(f"❌ Agent factory call failed for {handler_name}: {factory_error}")
                                    continue
                            else:
                                # Direct agent instance
                                cache_entry = {
                                    'instance': agent_factory,
                                    'creation_info': {
                                        'handler_name': handler_name,
                                        'discovery_call': discovery_call_id,
                                        'direct_instance': True,
                                        'time': time.time()
                                    }
                                }
                                _created_agents.set(agent_key, cache_entry)
                                handler_kwargs['agent'] = agent_factory
                        
                    except Exception as e:
                        logger.error(f"❌ Failed to process agent from factory '{agent_spec}': {e}")
                        continue
                else:
                    # Direct agent specification
                    handler_kwargs['agent'] = agent_spec
            
            # Filter to valid parameters only
            filtered_kwargs = {k: v for k, v in handler_kwargs.items() if k in valid_params}
            
            # Instantiate handler
            try:
                handler = handler_class(**filtered_kwargs)
                logger.debug(f"✅ [{discovery_call_id}] Handler instance created successfully: {handler_name}")
            except Exception as handler_error:
                logger.error(f"❌ Handler instantiation failed for {handler_name}: {handler_error}")
                continue
            
            # Determine if this should be default
            is_default = (
                config.get('default', False) or
                (default_handler_class is not None and handler_class is default_handler_class) or
                (not default_handler_name and not registered_names)
            )
            
            # Register with task manager
            try:
                _registered_handlers.add(handler_name)
                task_manager.register_handler(handler, default=is_default)
                registered_names.append(handler_name)
                
                if is_default:
                    default_handler_name = handler_name
                    
                logger.debug(f"✅ [{discovery_call_id}] Successfully registered handler '{handler_name}'{' (default)' if is_default else ''}")
                
            except Exception as registration_error:
                logger.error(f"❌ Handler registration failed for {handler_name}: {registration_error}")
                _registered_handlers.discard(handler_name)
                continue
                
        except Exception as exc:
            logger.error(f"❌ Unexpected error processing handler '{handler_name}': {exc}")
    
    # Final summary
    if registered_names:
        logger.debug(f"🎉 [{discovery_call_id}] Successfully registered {len(registered_names)} handlers: {', '.join(registered_names)}")
        if default_handler_name:
            logger.debug(f"🏆 [{discovery_call_id}] Default handler: {default_handler_name}")
    else:
        logger.debug(f"⚠️ [{discovery_call_id}] No handlers were successfully registered from configuration")

def get_discovery_stats() -> Dict[str, Any]:
    """Get statistics about discovery calls and agent creation with memory info."""
    # Check weak references and clean up dead ones
    live_agents = 0
    dead_agents = 0
    
    for agent_data in _created_agents._data.values():
        if 'weak_ref' in agent_data:
            if agent_data['weak_ref']() is not None:
                live_agents += 1
            else:
                dead_agents += 1
        else:
            live_agents += 1  # No weak ref, assume alive
    
    return {
        "discovery_calls": _discovery_calls.stats(),
        "created_agents": _created_agents.stats(),
        "agent_lifecycle": {
            "live_agents": live_agents,
            "dead_agents": dead_agents
        },
        "registered_handlers": len(_registered_handlers),
        "memory_management": {
            "cleanup_task_running": _cleanup_task is not None and not _cleanup_task.done(),
            "last_cleanup": {
                "discovery": _discovery_calls._last_cleanup,
                "agents": _created_agents._last_cleanup
            }
        }
    }

def cleanup_discovery_system():
    """Manual cleanup of discovery system (useful for tests)."""
    global _cleanup_task
    
    # Stop cleanup task
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()
        _cleanup_task = None
    
    # Clear caches
    _discovery_calls.clear()
    _created_agents.clear()
    _registered_handlers.clear()
    
    logger.info("Discovery system cleaned up")

__all__ = [
    "discover_handlers_in_package",
    "load_handlers_from_entry_points", 
    "discover_all_handlers",
    "register_discovered_handlers",
    "get_discovery_stats",
    "cleanup_discovery_system"
]