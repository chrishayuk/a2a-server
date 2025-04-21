# a2a_server/tasks/discovery.py
"""
Module for automatic discovery and registration of task handlers.
"""
import importlib
import inspect
import pkgutil
import logging
from typing import Iterator, Type, List, Optional

from a2a_server.tasks.task_handler import TaskHandler

logger = logging.getLogger(__name__)


def discover_handlers_in_package(package_name: str) -> Iterator[Type[TaskHandler]]:
    """
    Discover all TaskHandler subclasses in a package and its subpackages.

    Args:
        package_name: Fully qualified package name to search in

    Yields:
        TaskHandler subclasses found in the package
    """
    try:
        package = importlib.import_module(package_name)
        logger.debug(f"Scanning package {package_name} for handlers")
    except ImportError:
        logger.warning(f"Could not import package {package_name} for handler discovery")
        return

    # Find and import all modules recursively in the package
    prefix = package.__name__ + '.'
    modules_scanned = 0
    
    for _, name, is_pkg in pkgutil.walk_packages(package.__path__, prefix):
        modules_scanned += 1
        try:
            module = importlib.import_module(name)
            
            # Inspect all module members
            for attr_name, obj in inspect.getmembers(module, inspect.isclass):
                # Check if it's a TaskHandler subclass
                if issubclass(obj, TaskHandler) and obj is not TaskHandler:
                    # Check if it's marked as abstract
                    if hasattr(obj, 'abstract') and getattr(obj, 'abstract'):
                        logger.debug(f"Skipping abstract handler: {obj.__name__}")
                        continue
                        
                    # Check if it's abstract using inspect.isabstract 
                    if inspect.isabstract(obj):
                        logger.debug(f"Skipping abstract handler: {obj.__name__}")
                        continue
                        
                    logger.debug(f"Discovered handler: {obj.__name__} in {name}")
                    yield obj
        except (ImportError, AttributeError) as e:
            logger.warning(f"Error inspecting module {name}: {e}")
    
    logger.debug(f"Scanned {modules_scanned} modules in package {package_name}")


def load_handlers_from_entry_points() -> Iterator[Type[TaskHandler]]:
    """
    Discover TaskHandler implementations registered via entry_points.
    
    Looks for entry points in the group 'a2a.task_handlers'.
    
    Yields:
        TaskHandler subclasses found in entry points
    """
    logger.debug("Scanning entry points for handlers")
    
    try:
        from importlib.metadata import entry_points
        eps = entry_points(group='a2a.task_handlers')
        entry_points_count = 0
        handlers_found = 0
        
        for ep in eps:
            entry_points_count += 1
            try:
                handler_class = ep.load()
                if not inspect.isclass(handler_class):
                    logger.warning(f"Entry point {ep.name} did not load a class, got {type(handler_class)}")
                    continue
                    
                if not issubclass(handler_class, TaskHandler):
                    logger.warning(f"Entry point {ep.name} loaded {handler_class.__name__} which is not a TaskHandler subclass")
                    continue
                    
                if handler_class is TaskHandler:
                    continue
                
                # Check if it's marked as abstract
                if hasattr(handler_class, 'abstract') and getattr(handler_class, 'abstract'):
                    logger.debug(f"Skipping abstract handler: {handler_class.__name__}")
                    continue
                
                # Check if it's abstract using inspect.isabstract
                if inspect.isabstract(handler_class):
                    logger.debug(f"Skipping abstract handler: {handler_class.__name__}")
                    continue
                    
                logger.debug(f"Loaded handler {handler_class.__name__} from entry point {ep.name}")
                handlers_found += 1
                yield handler_class
            except Exception as e:
                logger.warning(f"Failed to load handler from entry point {ep.name}: {e}")
        
        logger.debug(f"Found {handlers_found} handlers from {entry_points_count} entry points")
                
    except ImportError:
        # Fallback for Python < 3.10
        try:
            import pkg_resources
            logger.debug("Using pkg_resources for entry point discovery")
            entry_points_count = 0
            handlers_found = 0
            
            for ep in pkg_resources.iter_entry_points(group='a2a.task_handlers'):
                entry_points_count += 1
                try:
                    handler_class = ep.load()
                    
                    if not inspect.isclass(handler_class):
                        logger.warning(f"Entry point {ep.name} did not load a class, got {type(handler_class)}")
                        continue
                        
                    if not issubclass(handler_class, TaskHandler):
                        logger.warning(f"Entry point {ep.name} loaded {handler_class.__name__} which is not a TaskHandler subclass")
                        continue
                        
                    if handler_class is TaskHandler:
                        continue
                    
                    # Check if it's marked as abstract
                    if hasattr(handler_class, 'abstract') and getattr(handler_class, 'abstract'):
                        logger.debug(f"Skipping abstract handler: {handler_class.__name__}")
                        continue
                    
                    # Check if it's abstract using inspect.isabstract
                    if inspect.isabstract(handler_class):
                        logger.debug(f"Skipping abstract handler: {handler_class.__name__}")
                        continue
                        
                    logger.debug(f"Loaded handler {handler_class.__name__} from entry point {ep.name}")
                    handlers_found += 1
                    yield handler_class
                except Exception as e:
                    logger.warning(f"Failed to load handler from entry point {ep.name}: {e}")
            
            logger.debug(f"Found {handlers_found} handlers from {entry_points_count} entry points")
        except ImportError:
            logger.warning("Neither importlib.metadata nor pkg_resources available")


def discover_all_handlers(
    packages: Optional[List[str]] = None
) -> List[Type[TaskHandler]]:
    """
    Discover all available task handlers from packages and entry points.
    
    Args:
        packages: Optional list of package names to search in
                 If None, will search in 'a2a_server.tasks.handlers'
    
    Returns:
        List of discovered TaskHandler classes
    """
    if packages is None:
        packages = ['a2a_server.tasks.handlers']
    
    logger.debug(f"Discovering handlers in packages: {packages}")
    handlers = []
    
    # Discover from packages
    for package in packages:
        pkg_handlers = list(discover_handlers_in_package(package))
        handlers.extend(pkg_handlers)
        logger.debug(f"Found {len(pkg_handlers)} handlers in package {package}")
    
    # Discover from entry points
    ep_handlers = list(load_handlers_from_entry_points())
    handlers.extend(ep_handlers)
    logger.debug(f"Found {len(ep_handlers)} handlers from entry points")
    
    logger.debug(f"Discovered {len(handlers)} handlers in total")
    return handlers

def register_discovered_handlers(
    task_manager,
    packages: Optional[List[str]] = None,
    default_handler_class: Optional[Type[TaskHandler]] = None
):
    """
    Discover and register all available handlers with a TaskManager.
    
    Args:
        task_manager: The TaskManager instance to register handlers with
        packages: Optional list of packages to search in
        default_handler_class: Optional class to use as the default handler
                             If None, the first handler is used as default
    """
    logger.debug("Starting handler discovery")
    handlers = discover_all_handlers(packages)
    
    if not handlers:
        logger.warning("No task handlers discovered")
        return
    
    # Instantiate and register each handler
    default_registered = False
    registered_count = 0
    default_handler_name = None
    non_default_handlers = []
    
    for handler_class in handlers:
        try:
            handler = handler_class()
            
            # If this is the specified default handler class, or no default has been
            # registered yet and no specific default was requested
            is_default = (
                (default_handler_class and handler_class is default_handler_class) or
                (not default_registered and default_handler_class is None)
            )
            
            task_manager.register_handler(handler, default=is_default)
            registered_count += 1
            
            if is_default:
                default_registered = True
                default_handler_name = handler.name
                logger.debug(f"Registered {handler.name} as default handler")
            else:
                non_default_handlers.append(handler.name)
                logger.debug(f"Registered handler: {handler.name}")
                
        except Exception as e:
            logger.error(f"Failed to instantiate handler {handler_class.__name__}: {e}")
    
    # Log a single summary message at INFO level
    if registered_count > 0:
        if default_handler_name:
            others = f", others: {', '.join(non_default_handlers)}" if non_default_handlers else ""
            logger.info(f"Registered {registered_count} task handlers (default: {default_handler_name}{others})")
        else:
            logger.info(f"Registered {registered_count} task handlers: {', '.join(non_default_handlers)}")
            