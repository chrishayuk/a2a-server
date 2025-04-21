# src/a2a_server/task_handler_registry.py
from typing import Optional, Dict

# a2a imports
from a2a_server.tasks.task_handler import TaskHandler

class TaskHandlerRegistry:
    """Registry for task handlers that can be dynamically selected."""
    def __init__(self):
        self._handlers: Dict[str, TaskHandler] = {}
        self._default_handler: Optional[str] = None
    
    def register(self, handler: TaskHandler, default: bool = False) -> None:
        """
        Register a new task handler.
        
        Args:
            handler: The handler to register
            default: Whether this should be the default handler
        """
        name = handler.name
        self._handlers[name] = handler
        
        if default or self._default_handler is None:
            self._default_handler = name
    
    def get(self, name: Optional[str] = None) -> TaskHandler:
        """
        Get a handler by name, or the default if name is None.
        
        Args:
            name: Optional handler name
            
        Returns:
            The requested handler
            
        Raises:
            KeyError: If the handler doesn't exist
        """
        if name is None:
            if self._default_handler is None:
                raise ValueError("No default handler registered")
            return self._handlers[self._default_handler]
        
        return self._handlers[name]
    
    def get_all(self) -> Dict[str, TaskHandler]:
        """Get all registered handlers."""
        return self._handlers.copy()