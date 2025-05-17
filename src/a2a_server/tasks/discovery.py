# a2a_server/tasks/discovery.py
"""
Automatic discovery and registration of TaskHandler subclasses.

Two discovery mechanisms are supported:

1. **Package scan** - walk a package tree (default
   ``a2a_server.tasks.handlers``) and yield every concrete ``TaskHandler``
   subclass it finds.

2. **Entry-points** - load classes registered under the
   ``a2a.task_handlers`` group.  Works with *importlib.metadata* (Python ≥ 3.10)
   and falls back to *pkg_resources* on older interpreters.

The module is safe to import in extremely slim Python images that ship
without *setuptools*: if ``import pkg_resources`` fails we register a tiny
stub so that unit-tests can still monkey-patch
``pkg_resources.iter_entry_points``.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
import sys
import types
from typing import Iterator, List, Optional, Type

from a2a_server.tasks.task_handler import TaskHandler

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
# ---------------------------------------------------------------------------


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

    # Older Pythons - fall back to setuptools’ pkg_resources
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
) -> None:
    """
    Instantiate and register every discovered handler with *task_manager*.

    The first registered handler (or the one explicitly passed via
    *default_handler_class*) becomes the default.
    """
    handlers = discover_all_handlers(packages)
    if not handlers:
        logger.warning("No task handlers discovered")
        return

    default_registered = False
    registered = 0
    default_name = None
    other_names: list[str] = []

    for cls in handlers:
        try:
            handler = cls()
            is_default = (
                (default_handler_class is not None and cls is default_handler_class)
                or (default_handler_class is None and not default_registered)
            )
            task_manager.register_handler(handler, default=is_default)  # type: ignore[arg-type]
            registered += 1
            if is_default:
                default_registered = True
                default_name = handler.name
            else:
                other_names.append(handler.name)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Failed to instantiate handler %s: %s", cls.__name__, exc)

    if registered:
        if default_name:
            logger.info(
                "Registered %d task handlers (default: %s%s)",
                registered,
                default_name,
                f', others: {", ".join(other_names)}' if other_names else "",
            )
        else:
            logger.info("Registered %d task handlers: %s", registered, ", ".join(other_names))
