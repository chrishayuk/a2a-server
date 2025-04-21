#!/usr/bin/env python3
# a2a/client/chat/chat_context.py
"""
Chat context for the A2A client interface.

Manages the client, connection, and state information.
"""
import asyncio
import logging
import os
import json
from typing import Dict, Any, Optional, List

# a2a client imports
from a2a.client.a2a_client import A2AClient
from a2a.json_rpc.json_rpc_errors import JSONRPCError
from a2a.json_rpc.spec import TaskQueryParams

logger = logging.getLogger("a2a-client")

class ChatContext:
    """
    Manages the state for the A2A client chat interface.
    
    Handles connection to the A2A server, client configuration,
    and maintains shared state across components.
    """
    
    def __init__(self, base_url: Optional[str] = None, config_file: Optional[str] = None):
        """
        Initialize the chat context.
        
        Args:
            base_url: Optional base URL for the A2A server
            config_file: Optional path to a configuration file
        """
        # Connection info
        self.base_url = base_url or "http://localhost:8000"
        self.config_file = config_file
        
        # Client instances
        self.client = None
        self.streaming_client = None
        
        # State flags
        self.exit_requested = False
        self.verbose_mode = False
        self.debug_mode = False
        
        # History
        self.command_history = []
        
        # Server names (from config)
        self.server_names = {}
        
        # Tasks
        self.last_task_id = None
    
    async def initialize(self) -> bool:
        """
        Initialize the chat context and establish connections.
        
        Returns:
            True if initialization was successful, False otherwise
        """
        # Load config if provided
        if self.config_file:
            try:
                self._load_config()
            except Exception as e:
                logger.error(f"Error loading config: {e}")
                return False
        
        # Connect to the server
        try:
            await self._connect_to_server()
            return True
        except Exception as e:
            logger.error(f"Error connecting to server: {e}")
            return False
    
    def _load_config(self) -> None:
        """
        Load configuration from file.
        """
        config_path = os.path.expanduser(self.config_file)
        
        if not os.path.exists(config_path):
            logger.warning(f"Config file not found: {config_path}")
            return
        
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            # Extract server names
            self.server_names = config.get("servers", {})
            logger.info(f"Loaded {len(self.server_names)} servers from config")
            
            # If a base URL is not specified and we have servers, use the first one
            if not self.base_url and self.server_names:
                first_server = next(iter(self.server_names.values()))
                self.base_url = first_server
                logger.info(f"Using first server from config: {self.base_url}")
                
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in config file: {config_path}")
        except Exception as e:
            logger.error(f"Error loading config: {e}")
    
    async def _connect_to_server(self) -> None:
        """
        Establish connection to the A2A server.
        """
        rpc_url = self.base_url + "/rpc"
        events_url = self.base_url + "/events"
        
        # Create standard HTTP client
        try:
            self.client = A2AClient.over_http(rpc_url)
            
            # Try a simple ping to verify connection
            logger.debug(f"Testing connection to {rpc_url}...")
            
            try:
                # Create a proper TaskQueryParams object instead of a raw dict
                params = TaskQueryParams(id="ping-test-000")
                await self.client.get_task(params)
            except JSONRPCError as e:
                # This is expected - we just wanted to verify the server responds
                if "not found" in str(e).lower():
                    logger.info(f"Successfully connected to {self.base_url}")
                else:
                    # Some other error
                    logger.warning(f"Connected but received unexpected error: {e}")
            
            # Create SSE client for streaming operations
            self.streaming_client = A2AClient.over_sse(rpc_url, events_url)
            
        except Exception as e:
            logger.error(f"Error connecting to server: {e}")
            raise
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the context to a dictionary for command handlers.
        
        Returns:
            Dictionary representation of the context
        """
        return {
            "base_url": self.base_url,
            "client": self.client,
            "streaming_client": self.streaming_client,
            "verbose_mode": self.verbose_mode,
            "debug_mode": self.debug_mode,
            "exit_requested": self.exit_requested,
            "command_history": self.command_history,
            "server_names": self.server_names,
            "last_task_id": self.last_task_id
        }
    
    def update_from_dict(self, context_dict: Dict[str, Any]) -> None:
        """
        Update the context from a dictionary (after command execution).
        
        Args:
            context_dict: Dictionary with updated context values
        """
        # Update connection info
        if "base_url" in context_dict:
            self.base_url = context_dict["base_url"]
        
        # Update clients
        if "client" in context_dict:
            self.client = context_dict["client"]
        if "streaming_client" in context_dict:
            self.streaming_client = context_dict["streaming_client"]
        
        # Update state flags
        if "verbose_mode" in context_dict:
            self.verbose_mode = context_dict["verbose_mode"]
        if "debug_mode" in context_dict:
            self.debug_mode = context_dict["debug_mode"]
        if "exit_requested" in context_dict:
            self.exit_requested = context_dict["exit_requested"]
        
        # Update history
        if "command_history" in context_dict:
            self.command_history = context_dict["command_history"]
        
        # Update server names
        if "server_names" in context_dict:
            self.server_names = context_dict["server_names"]
        
        # Update task info
        if "last_task_id" in context_dict:
            self.last_task_id = context_dict["last_task_id"]
    
    async def close(self) -> None:
        """
        Close all connections and clean up resources.
        """
        # Close streaming client if available
        if self.streaming_client and hasattr(self.streaming_client.transport, "close"):
            await self.streaming_client.transport.close()
        
        # Close main client if available
        if self.client and hasattr(self.client.transport, "close"):
            await self.client.transport.close()