# a2a_server/tasks/discovery.py
"""
Fixed automatic discovery and registration of TaskHandler subclasses.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
import sys
import types
from typing import Iterator, List, Optional, Type, Dict, Any

from a2a_server.tasks.handlers.task_handler import TaskHandler

logger = logging.getLogger(__name__)

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
        logger.warning("Could not import package %s for handler discovery", package_name)
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
            logger.warning("Error inspecting module %s: %s", modname, exc)

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
                logger.warning(
                    "Entry-point %s did not resolve to a concrete TaskHandler (got %r)",
                    ep.name,
                    cls,
                )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to load handler from entry-point %s: %s", ep.name, exc)

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

    logger.info("Discovered %d task handlers in total", len(handlers))
    return handlers


def register_discovered_handlers(
    task_manager,
    packages: Optional[List[str]] = None,
    default_handler_class: Optional[Type[TaskHandler]] = None,
    extra_kwargs: Optional[Dict[str, Any]] = None,
    **explicit_handlers
) -> None:
    """
    Enhanced handler registration with comprehensive configuration support.
    
    Args:
        task_manager: The task manager to register handlers with
        packages: List of packages to scan for handlers
        default_handler_class: Optional specific class to use as default
        extra_kwargs: Additional keyword arguments to pass to handler constructors
        **explicit_handlers: Explicit handler configurations from YAML
    """
    extra_kwargs = extra_kwargs or {}
    
    # 🔧 CRITICAL FIX: Track which agent factories have been called to prevent double creation
    _created_agents = {}
    
    # Register explicit handlers from configuration first
    if explicit_handlers:
        logger.info(f"Registering {len(explicit_handlers)} explicit handlers from configuration")
        _register_explicit_handlers(task_manager, explicit_handlers, default_handler_class, _created_agents)
    
    # Only do package discovery if explicitly requested
    if packages:
        handlers = discover_all_handlers(packages)
        if not handlers:
            logger.warning("No task handlers discovered from packages")
            return

        registered = 0
        default_name = None
        other_names: list[str] = []

        for cls in handlers:
            # Skip if this handler was already registered explicitly
            handler_name = getattr(cls, '_name', cls.__name__.lower().replace('handler', ''))
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
                logger.info(
                    "Registered %d discovered task handlers (default: %s%s)",
                    registered,
                    default_name,
                    f', others: {", ".join(other_names)}' if other_names else "",
                )
            else:
                logger.info("Registered %d discovered task handlers: %s", registered, ", ".join(other_names))


def _register_explicit_handlers(
    task_manager, 
    explicit_handlers: Dict[str, Dict[str, Any]], 
    default_handler_class: Optional[Type[TaskHandler]] = None,
    created_agents: Optional[Dict[str, Any]] = None
) -> None:
    """Register handlers explicitly defined in configuration."""
    default_handler_name = None
    registered_names = []
    
    # 🔧 CRITICAL FIX: Track created agents to prevent double creation
    if created_agents is None:
        created_agents = {}
    
    logger.debug(f"Processing {len(explicit_handlers)} explicit handlers")
    
    for handler_name, config in explicit_handlers.items():
        if not isinstance(config, dict):
            continue
            
        try:
            # Extract handler type (class path)
            handler_type = config.get('type')
            if not handler_type:
                logger.error(f"Handler '{handler_name}' missing 'type' configuration")
                continue
            
            # Import handler class
            try:
                module_path, _, class_name = handler_type.rpartition('.')
                module = importlib.import_module(module_path)
                handler_class = getattr(module, class_name)
                logger.debug(f"Imported handler class: {handler_class.__name__}")
            except (ImportError, AttributeError) as e:
                logger.error(f"Failed to import handler class '{handler_type}': {e}")
                continue
            
            # 🔧 CRITICAL FIX: Check if this is an agent-based handler
            is_agent_handler = (
                'AgentHandler' in class_name or 
                'GoogleADKHandler' in class_name or
                hasattr(handler_class, 'requires_agent') and handler_class.requires_agent
            )
            
            # Extract agent specification (only required for agent-based handlers)
            agent_spec = config.get('agent')
            if is_agent_handler and not agent_spec:
                logger.error(f"Agent-based handler '{handler_name}' missing 'agent' configuration")
                continue
            elif not is_agent_handler and agent_spec:
                logger.warning(f"Standalone handler '{handler_name}' has unnecessary 'agent' configuration - ignoring")
            
            # Prepare constructor arguments
            handler_kwargs = config.copy()
            handler_kwargs.pop('type', None)  # Remove meta fields
            handler_kwargs.pop('agent_card', None)
            
            # Set the name explicitly
            handler_kwargs['name'] = handler_name
            
            # Debug constructor parameters
            sig = inspect.signature(handler_class.__init__)
            valid_params = set(sig.parameters.keys()) - {"self"}
            
            # Filter to valid parameters
            filtered_kwargs = {k: v for k, v in handler_kwargs.items() if k in valid_params}
            
            # 🔧 CRITICAL FIX: Only process agent for agent-based handlers
            if is_agent_handler and agent_spec:
                if isinstance(agent_spec, str):
                    try:
                        # Create a unique key for this agent configuration
                        agent_config = {k: v for k, v in config.items() 
                                       if k not in ['type', 'name', 'agent', 'agent_card']}
                        agent_key = f"{agent_spec}#{hash(frozenset(agent_config.items()))}"
                        
                        # Check if we've already created this exact agent
                        if agent_key in created_agents:
                            logger.debug(f"Reusing existing agent for {handler_name}")
                            filtered_kwargs['agent'] = created_agents[agent_key]
                        else:
                            # Import and create the agent
                            agent_module_path, _, agent_func_name = agent_spec.rpartition('.')
                            agent_module = importlib.import_module(agent_module_path)
                            agent_factory = getattr(agent_module, agent_func_name)
                            
                            if callable(agent_factory):
                                logger.debug(f"Creating new agent for {handler_name} with {len(agent_config)} parameters")
                                
                                # Call factory with configuration
                                agent_instance = agent_factory(**agent_config)
                                
                                # Cache the created agent
                                created_agents[agent_key] = agent_instance
                                filtered_kwargs['agent'] = agent_instance
                                
                                # Verify session configuration
                                if hasattr(agent_instance, 'enable_sessions'):
                                    logger.debug(f"Agent {handler_name} enable_sessions: {agent_instance.enable_sessions}")
                            else:
                                # Direct agent instance
                                created_agents[agent_key] = agent_factory
                                filtered_kwargs['agent'] = agent_factory
                        
                    except Exception as e:
                        logger.error(f"Failed to create agent from factory '{agent_spec}': {e}")
                        continue
                else:
                    # Direct agent specification
                    filtered_kwargs['agent'] = agent_spec
            
            # 🎯 NEW: Log handler type for debugging
            if is_agent_handler:
                logger.debug(f"Registering agent-based handler: {handler_name}")
            else:
                logger.debug(f"Registering standalone handler: {handler_name}")
            
            # Instantiate handler
            handler = handler_class(**filtered_kwargs)
            
            # Determine if this should be default
            is_default = (
                config.get('default', False) or
                (default_handler_class is not None and handler_class is default_handler_class) or
                (not default_handler_name and not registered_names)
            )
            
            # Register with task manager
            task_manager.register_handler(handler, default=is_default)
            registered_names.append(handler_name)
            
            if is_default:
                default_handler_name = handler_name
                
            logger.info(f"Registered handler '{handler_name}'{' (default)' if is_default else ''}")
            
        except Exception as exc:
            logger.error(f"Failed to register handler '{handler_name}': {exc}")
    
    if registered_names:
        logger.info(f"Successfully registered {len(registered_names)} handlers: {', '.join(registered_names)}")
        if default_handler_name:
            logger.info(f"Default handler: {default_handler_name}")       

__all__ = [
    "discover_handlers_in_package",
    "load_handlers_from_entry_points", 
    "discover_all_handlers",
    "register_discovered_handlers"
]