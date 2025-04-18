# a2a/server/tasks/discovery.py
"""
Module for automatic discovery and registration of task handlers.
"""
import importlib
import inspect
import pkgutil
import logging
from typing import Iterator, Type, List, Optional

from a2a.server.tasks.task_handler import TaskHandler

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
    except ImportError:
        logger.warning(f"Could not import package {package_name} for handler discovery")
        return

    # Find and import all modules recursively in the package
    prefix = package.__name__ + '.'
    for _, name, is_pkg in pkgutil.walk_packages(package.__path__, prefix):
        try:
            module = importlib.import_module(name)
            
            # Inspect all module members
            for attr_name, obj in inspect.getmembers(module, inspect.isclass):
                # Check if it's a TaskHandler subclass
                if issubclass(obj, TaskHandler) and obj is not TaskHandler:
                    # Log for debugging
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


def load_handlers_from_entry_points() -> Iterator[Type[TaskHandler]]:
    """
    Discover TaskHandler implementations registered via entry_points.
    
    Looks for entry points in the group 'a2a.task_handlers'.
    
    Yields:
        TaskHandler subclasses found in entry points
    """
    try:
        from importlib.metadata import entry_points
        eps = entry_points(group='a2a.task_handlers')
        
        for ep in eps:
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
                yield handler_class
            except Exception as e:
                logger.warning(f"Failed to load handler from entry point {ep.name}: {e}")
                
    except ImportError:
        # Fallback for Python < 3.10
        try:
            import pkg_resources
            for ep in pkg_resources.iter_entry_points(group='a2a.task_handlers'):
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
                    yield handler_class
                except Exception as e:
                    logger.warning(f"Failed to load handler from entry point {ep.name}: {e}")
        except ImportError:
            logger.warning("Neither importlib.metadata nor pkg_resources available")


def discover_all_handlers(
    packages: Optional[List[str]] = None
) -> List[Type[TaskHandler]]:
    """
    Discover all available task handlers from packages and entry points.
    
    Args:
        packages: Optional list of package names to search in
                 If None, will search in 'a2a.server.tasks.handlers'
    
    Returns:
        List of discovered TaskHandler classes
    """
    if packages is None:
        packages = ['a2a.server.tasks.handlers']
    
    handlers = []
    
    # Discover from packages
    for package in packages:
        handlers.extend(discover_handlers_in_package(package))
    
    # Discover from entry points
    handlers.extend(load_handlers_from_entry_points())
    
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
    handlers = discover_all_handlers(packages)
    
    if not handlers:
        logger.warning("No task handlers discovered")
        return
    
    # Instantiate and register each handler
    default_registered = False
    
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
            
            if is_default:
                default_registered = True
                logger.info(f"Registered {handler.name} as default handler")
            else:
                logger.info(f"Registered handler: {handler.name}")
                
        except Exception as e:
            logger.error(f"Failed to instantiate handler {handler_class.__name__}: {e}")
    
    logger.info(f"Registered {len(handlers)} task handlers")