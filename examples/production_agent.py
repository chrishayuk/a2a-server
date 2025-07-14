#!/usr/bin/env python3
"""
Production Resilient A2A Agent
==============================

This script demonstrates how to run a production-ready resilient agent
that can handle MCP failures, agent crashes, and other real-world issues.

Usage:
    python production_agent.py [--config config.yaml] [--demo]
"""

import asyncio
import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional
import yaml

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('resilient_agent.log')
    ]
)
logger = logging.getLogger(__name__)


def create_production_agent(**config) -> 'ChukAgent':
    """
    Factory function to create a production ChukAgent with the given configuration.
    This function is referenced in the YAML config.
    """
    try:
        from a2a_server.tasks.handlers.chuk.chuk_agent import ChukAgent
        
        logger.info(f"Creating production agent: {config.get('name', 'unnamed')}")
        
        # Create agent with production settings
        agent = ChukAgent(
            name=config.get('name', 'ProductionAgent'),
            description=config.get('description', 'Production AI agent'),
            provider=config.get('provider', 'openai'),
            model=config.get('model', 'gpt-4'),
            instruction=config.get('instruction', 'You are a helpful assistant.'),
            
            # Tool configuration
            enable_tools=config.get('enable_tools', True),
            debug_tools=config.get('debug_tools', False),
            tool_timeout=config.get('tool_timeout', 30.0),
            max_concurrency=config.get('max_concurrency', 3),
            
            # MCP configuration
            mcp_transport=config.get('mcp_transport', 'stdio'),
            mcp_config_file=config.get('mcp_config_file'),
            mcp_servers=config.get('mcp_servers', []),
            
            # Session configuration
            enable_sessions=config.get('enable_sessions', True),
            infinite_context=config.get('infinite_context', True),
            token_threshold=config.get('token_threshold', 4000),
            max_turns_per_segment=config.get('max_turns_per_segment', 50)
        )
        
        logger.info(f"✅ Production agent created successfully: {agent.name}")
        return agent
        
    except ImportError as e:
        logger.error(f"❌ Failed to import ChukAgent: {e}")
        # Return a mock agent for demonstration
        return MockProductionAgent(**config)
    except Exception as e:
        logger.error(f"❌ Failed to create production agent: {e}")
        raise


class MockProductionAgent:
    """
    Mock agent for demonstration when ChukAgent is not available.
    """
    
    def __init__(self, **config):
        self.name = config.get('name', 'MockAgent')
        self.config = config
        self.call_count = 0
        self.failure_simulation = False
        
    async def complete(self, messages, use_tools=True, session_id=None):
        """Mock completion with failure simulation."""
        self.call_count += 1
        
        # Simulate occasional failures
        if self.failure_simulation and self.call_count % 8 == 0:
            raise ConnectionError("Simulated MCP connection failure")
        
        user_content = "test"
        for msg in messages:
            if msg.get('role') == 'user':
                user_content = msg.get('content', 'test')
                break
        
        return {
            "content": f"Mock response from {self.name}: {user_content}",
            "tool_calls": [],
            "tool_results": [],
            "usage": {"total_tokens": 50}
        }
    
    async def initialize_tools(self):
        """Mock tool initialization."""
        if self.failure_simulation and self.call_count % 5 == 0:
            raise ConnectionError("Simulated tool initialization failure")
        
    def get_health_status(self):
        """Mock health status."""
        return {
            "agent_name": self.name,
            "status": "healthy",
            "call_count": self.call_count,
            "failure_simulation": self.failure_simulation
        }


class ProductionAgentManager:
    """
    Manages a production agent with monitoring, health checks, and recovery.
    """
    
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = self.load_config()
        self.agent = None
        self.handler = None
        self.running = False
        self.health_check_task = None
        self.stats = {
            "requests_processed": 0,
            "errors_encountered": 0,
            "circuit_breaker_opens": 0,
            "recovery_attempts": 0,
            "uptime_start": time.time()
        }
    
    def load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info(f"✅ Configuration loaded from {self.config_path}")
            return config
        except Exception as e:
            logger.error(f"❌ Failed to load config from {self.config_path}: {e}")
            # Return default configuration
            return self.get_default_config()
    
    def get_default_config(self) -> Dict[str, Any]:
        """Get default configuration when file loading fails."""
        return {
            "handler": {
                "type": "ChukAgentHandler",
                "name": "default_agent",
                "circuit_breaker_threshold": 3,
                "circuit_breaker_timeout": 60.0,
                "task_timeout": 120.0,
                "max_retry_attempts": 2
            },
            "agent_config": {
                "name": "DefaultAgent",
                "description": "Default resilient agent",
                "enable_tools": False,  # Disable tools in default config
                "enable_sessions": False
            },
            "monitoring": {
                "health_check_interval": 30,
                "log_level": "INFO"
            }
        }
    
    async def initialize_agent(self):
        """Initialize the agent and handler."""
        try:
            # Create agent using factory function
            agent_config = self.config.get('agent_config', {})
            self.agent = create_production_agent(**agent_config)
            
            # Try to create handler if ChukAgentHandler is available
            try:
                from a2a_server.tasks.handlers.chuk.chuk_agent_handler import ChukAgentHandler
                
                handler_config = self.config.get('handler', {})
                self.handler = ChukAgentHandler(
                    agent=self.agent,
                    **{k: v for k, v in handler_config.items() if k != 'type'}
                )
                logger.info("✅ ChukAgentHandler initialized successfully")
                
            except ImportError:
                logger.warning("⚠️ ChukAgentHandler not available, using agent directly")
                self.handler = self.agent
            
            logger.info(f"✅ Agent system initialized: {self.agent.name}")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize agent: {e}")
            raise
    
    async def start_health_monitoring(self):
        """Start background health monitoring."""
        async def health_check_loop():
            interval = self.config.get('monitoring', {}).get('health_check_interval', 30)
            
            while self.running:
                try:
                    # Check agent health
                    if hasattr(self.agent, 'get_health_status'):
                        health = self.agent.get_health_status()
                        logger.debug(f"🏥 Agent health: {health}")
                    
                    # Check handler health if available
                    if hasattr(self.handler, 'get_health_status') and self.handler != self.agent:
                        handler_health = self.handler.get_health_status()
                        logger.debug(f"🏥 Handler health: {handler_health}")
                    
                    # Log system stats
                    uptime = time.time() - self.stats["uptime_start"]
                    logger.info(f"📊 System stats: {self.stats['requests_processed']} requests, "
                              f"{self.stats['errors_encountered']} errors, "
                              f"{uptime:.1f}s uptime")
                    
                except Exception as e:
                    logger.error(f"❌ Health check failed: {e}")
                    self.stats["errors_encountered"] += 1
                
                await asyncio.sleep(interval)
        
        self.health_check_task = asyncio.create_task(health_check_loop())
        logger.info("🏥 Health monitoring started")
    
    async def process_request(self, user_message: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Process a user request with error handling and monitoring."""
        start_time = time.time()
        
        try:
            self.stats["requests_processed"] += 1
            
            # Prepare messages
            messages = [
                {"role": "system", "content": "You are a helpful and resilient AI assistant."},
                {"role": "user", "content": user_message}
            ]
            
            # Process through handler if available, otherwise direct to agent
            if hasattr(self.handler, 'process_task'):
                # Use A2A handler interface
                from a2a_json_rpc.spec import Message, TextPart, Role
                
                a2a_message = Message(
                    role=Role.user,
                    parts=[TextPart(type="text", text=user_message)]
                )
                
                # Collect events from handler
                events = []
                async for event in self.handler.process_task(
                    f"req_{self.stats['requests_processed']}", 
                    a2a_message, 
                    session_id
                ):
                    events.append(event)
                
                # Extract final response from events
                response_content = "Task completed"
                for event in events:
                    if hasattr(event, 'artifact') and event.artifact:
                        for part in event.artifact.parts:
                            if hasattr(part, 'text'):
                                response_content = part.text
                                break
                            elif hasattr(part, 'model_dump'):
                                part_data = part.model_dump()
                                if 'text' in part_data:
                                    response_content = part_data['text']
                                    break
                
                result = {"content": response_content}
                
            else:
                # Use direct agent interface
                result = await self.agent.complete(messages, session_id=session_id)
            
            processing_time = time.time() - start_time
            logger.info(f"✅ Request processed in {processing_time:.2f}s")
            
            return {
                "success": True,
                "response": result.get("content", "No response"),
                "processing_time": processing_time,
                "tool_calls": result.get("tool_calls", []),
                "session_id": session_id
            }
            
        except Exception as e:
            self.stats["errors_encountered"] += 1
            processing_time = time.time() - start_time
            
            logger.error(f"❌ Request failed after {processing_time:.2f}s: {e}")
            
            return {
                "success": False,
                "error": str(e),
                "processing_time": processing_time,
                "session_id": session_id
            }
    
    async def run_demo_scenario(self):
        """Run a demonstration of resilient behavior."""
        logger.info("🎭 Starting resilient agent demonstration...")
        
        # Enable failure simulation if using mock agent
        if hasattr(self.agent, 'failure_simulation'):
            self.agent.failure_simulation = True
        
        demo_requests = [
            "Hello! Can you introduce yourself?",
            "What's the weather like today?",
            "Calculate 15 * 23 + 7",
            "Tell me about your capabilities",
            "What happens when your tools fail?",
            "Can you remember our conversation?",
            "How do you handle errors?",
            "What's 2 + 2?",
            "Test your resilience features",
            "Final test message"
        ]
        
        session_id = "demo_session_123"
        
        for i, request in enumerate(demo_requests):
            logger.info(f"🔄 Demo request {i + 1}: {request}")
            
            result = await self.process_request(request, session_id)
            
            if result["success"]:
                logger.info(f"✅ Response: {result['response'][:100]}...")
            else:
                logger.warning(f"❌ Failed: {result['error']}")
            
            # Brief pause between requests
            await asyncio.sleep(2)
        
        logger.info("🎉 Demo completed!")
        
        # Print final stats
        uptime = time.time() - self.stats["uptime_start"]
        success_rate = (self.stats["requests_processed"] - self.stats["errors_encountered"]) / self.stats["requests_processed"] * 100
        
        print(f"\n📊 FINAL STATISTICS:")
        print(f"  Requests processed: {self.stats['requests_processed']}")
        print(f"  Errors encountered: {self.stats['errors_encountered']}")
        print(f"  Success rate: {success_rate:.1f}%")
        print(f"  Total uptime: {uptime:.1f} seconds")
    
    async def start(self, demo_mode: bool = False):
        """Start the agent manager."""
        logger.info("🚀 Starting production agent manager...")
        
        try:
            # Initialize system
            await self.initialize_agent()
            self.running = True
            
            # Start monitoring
            await self.start_health_monitoring()
            
            if demo_mode:
                # Run demonstration
                await self.run_demo_scenario()
            else:
                # Run in production mode (would typically listen for requests)
                logger.info("🔄 Agent running in production mode...")
                logger.info("   (In real deployment, this would handle incoming requests)")
                
                # Simple example loop
                while self.running:
                    await asyncio.sleep(10)
                    logger.info("💓 Agent heartbeat - system running normally")
            
        except KeyboardInterrupt:
            logger.info("👋 Shutdown requested by user")
        except Exception as e:
            logger.error(f"❌ Agent manager failed: {e}")
            raise
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Gracefully shutdown the agent manager."""
        logger.info("🛑 Shutting down agent manager...")
        
        self.running = False
        
        # Cancel health monitoring
        if self.health_check_task:
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass
        
        # Shutdown agent if it has cleanup methods
        if hasattr(self.agent, 'shutdown'):
            try:
                await self.agent.shutdown()
            except Exception as e:
                logger.warning(f"⚠️ Agent shutdown error: {e}")
        
        logger.info("✅ Agent manager shutdown complete")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Production Resilient A2A Agent")
    parser.add_argument("--config", default="production_resilient_agent.yaml", 
                       help="Configuration file path")
    parser.add_argument("--demo", action="store_true", 
                       help="Run in demonstration mode")
    
    args = parser.parse_args()
    
    # Setup signal handlers for graceful shutdown
    manager = None
    
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}")
        if manager:
            asyncio.create_task(manager.shutdown())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        manager = ProductionAgentManager(args.config)
        await manager.start(demo_mode=args.demo)
    except Exception as e:
        logger.error(f"❌ Production agent failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Set environment variables for demo if not set
    os.environ.setdefault("WEATHER_API_KEY", "demo_weather_key_123")
    os.environ.setdefault("SEARCH_API_KEY", "demo_search_key_456")
    os.environ.setdefault("ALERT_WEBHOOK_URL", "https://hooks.slack.com/demo")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Agent stopped by user")
    except Exception as e:
        print(f"\n❌ Agent failed: {e}")
        sys.exit(1)