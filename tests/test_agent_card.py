#!/usr/bin/env python3
# tests/test_agent_card.py
"""
Comprehensive unit tests for a2a_server.agent_card module.

Tests the agent card creation and management including:
- Creating agent cards from handler configurations
- Default value handling and fallbacks
- URL generation and custom URL handling
- Skills and capabilities configuration
- Error handling and edge cases
- Batch card generation from handlers config
"""

import pytest
from unittest.mock import patch
from typing import Dict, Any

from a2a_server.agent_card import (
    create_agent_card,
    get_agent_cards,
)
from a2a_json_rpc.spec import (
    AgentCard as SpecAgentCard,
    AgentCapabilities,
    AgentSkill,
)


class TestCreateAgentCard:
    """Test the create_agent_card function."""

    def test_create_agent_card_with_full_config(self):
        """Test creating an agent card with complete configuration."""
        handler_config = {
            "type": "TestHandler",
            "agent_card": {
                "name": "Pirate Agent",
                "description": "Converts your text into salty pirate-speak",
                "version": "0.2.1",
                "documentationUrl": "https://pirate.example.com/docs",
                "capabilities": {
                    "streaming": True,
                    "pushNotifications": True,
                    "stateTransitionHistory": True
                },
                "defaultInputModes": ["text/plain", "text/markdown"],
                "defaultOutputModes": ["text/plain", "application/json"],
                "skills": [
                    {
                        "id": "pirate-talk",
                        "name": "Pirate Talk",
                        "description": "Turn any message into pirate lingo",
                        "tags": ["pirate", "fun", "language"],
                        "examples": ["Arrr! Give me yer loot!", "Shiver me timbers!"]
                    },
                    {
                        "id": "treasure-hunt",
                        "name": "Treasure Hunt",
                        "description": "Find hidden treasures in text",
                        "tags": ["pirate", "search"],
                        "examples": ["Find the treasure in this map"]
                    }
                ]
            }
        }

        card = create_agent_card(
            handler_name="pirate_agent",
            base_url="https://api.example.com",
            handler_cfg=handler_config
        )

        # Basic properties
        assert card.name == "Pirate Agent"
        assert card.description == "Converts your text into salty pirate-speak"
        assert card.url == "https://api.example.com/pirate_agent"
        assert card.version == "0.2.1"
        # Check documentation URL
        assert card.documentation_url == "https://pirate.example.com/docs"

        # Capabilities - use snake_case field names
        assert card.capabilities.streaming is True
        assert card.capabilities.push_notifications is True
        assert card.capabilities.state_transition_history is True

        # Input/Output modes - use snake_case field names
        assert card.default_input_modes == ["text/plain", "text/markdown"]
        assert card.default_output_modes == ["text/plain", "application/json"]

        # Skills
        assert len(card.skills) == 2
        
        skill1 = card.skills[0]
        assert skill1.id == "pirate-talk"
        assert skill1.name == "Pirate Talk"
        assert skill1.description == "Turn any message into pirate lingo"
        assert skill1.tags == ["pirate", "fun", "language"]
        assert skill1.examples == ["Arrr! Give me yer loot!", "Shiver me timbers!"]
        
        skill2 = card.skills[1]
        assert skill2.id == "treasure-hunt"
        assert skill2.name == "Treasure Hunt"

    def test_create_agent_card_with_minimal_config(self):
        """Test creating an agent card with minimal configuration."""
        handler_config = {
            "type": "MinimalHandler"
        }

        card = create_agent_card(
            handler_name="weather_agent",
            base_url="http://localhost:8000",
            handler_cfg=handler_config
        )

        # Should use defaults
        assert card.name == "Weather Agent"  # Title-cased with underscores replaced
        assert card.description == "A2A handler for weather_agent"
        assert card.url == "http://localhost:8000/weather_agent"
        assert card.version == "1.0.0"
        # documentationUrl should be None
        assert card.documentation_url is None

        # Default capabilities
        assert card.capabilities.streaming is True
        assert card.capabilities.push_notifications is False
        assert card.capabilities.state_transition_history is False

        # Default input/output
        assert card.default_input_modes == ["text/plain"]
        assert card.default_output_modes == ["text/plain"]

        # Default skill
        assert len(card.skills) == 1
        skill = card.skills[0]
        assert skill.id == "weather_agent-default"
        assert skill.name == "Weather Agent"
        assert skill.description == "A2A handler for weather_agent"
        assert skill.tags == ["weather_agent"]

    def test_create_agent_card_with_custom_url(self):
        """Test creating an agent card with custom URL override."""
        handler_config = {
            "agent_card": {
                "url": "https://custom-domain.com/special-path",
                "name": "Custom Agent"
            }
        }

        card = create_agent_card(
            handler_name="custom_agent",
            base_url="http://localhost:8000",
            handler_cfg=handler_config
        )

        # Should use custom URL instead of base_url + handler_name
        assert card.url == "https://custom-domain.com/special-path"
        assert card.name == "Custom Agent"

    def test_create_agent_card_with_partial_capabilities(self):
        """Test creating agent card with partial capabilities configuration."""
        handler_config = {
            "agent_card": {
                "capabilities": {
                    "streaming": False,
                    "pushNotifications": True
                    # stateTransitionHistory not specified
                }
            }
        }

        card = create_agent_card(
            handler_name="partial_agent",
            base_url="http://localhost:8000",
            handler_cfg=handler_config
        )

        # Specified values should be used, missing should use defaults
        assert card.capabilities.streaming is False
        assert card.capabilities.push_notifications is True
        assert card.capabilities.state_transition_history is False  # default

    def test_create_agent_card_with_empty_skills(self):
        """Test creating agent card with empty skills array."""
        handler_config = {
            "agent_card": {
                "skills": []
            }
        }

        card = create_agent_card(
            handler_name="no_skills_agent",
            base_url="http://localhost:8000",
            handler_cfg=handler_config
        )

        # Should create default skill when skills array is empty
        assert len(card.skills) == 1
        assert card.skills[0].id == "no_skills_agent-default"

    def test_create_agent_card_handler_name_formatting(self):
        """Test various handler name formatting scenarios."""
        test_cases = [
            ("simple_agent", "Simple Agent"),
            ("multi_word_agent_name", "Multi Word Agent Name"), 
            ("already_formatted", "Already Formatted"),
            ("UPPERCASE_AGENT", "Uppercase Agent"),  # title() converts to title case
            ("mixed_Case_Agent", "Mixed Case Agent"),
        ]

        for handler_name, expected_name in test_cases:
            card = create_agent_card(
                handler_name=handler_name,
                base_url="http://localhost:8000",
                handler_cfg={}
            )
            assert card.name == expected_name

    def test_create_agent_card_with_skill_without_optional_fields(self):
        """Test creating agent card with skills missing optional fields."""
        handler_config = {
            "agent_card": {
                "skills": [
                    {
                        "id": "basic-skill",
                        "name": "Basic Skill",
                        "description": "A basic skill without optional fields"
                        # tags and examples not specified
                    }
                ]
            }
        }

        card = create_agent_card(
            handler_name="basic_agent",
            base_url="http://localhost:8000",
            handler_cfg=handler_config
        )

        skill = card.skills[0]
        assert skill.id == "basic-skill"
        assert skill.name == "Basic Skill"
        assert skill.description == "A basic skill without optional fields"
        # Optional fields should be handled by the AgentSkill model


class TestGetAgentCards:
    """Test the get_agent_cards function."""

    def test_get_agent_cards_with_multiple_handlers(self):
        """Test getting agent cards for multiple handlers."""
        handlers_config = {
            "use_discovery": True,
            "handler_packages": ["some.package"],
            "default_handler": "weather_agent",
            "weather_agent": {
                "type": "WeatherHandler",
                "agent_card": {
                    "name": "Weather Agent",
                    "description": "Provides weather information"
                }
            },
            "pirate_agent": {
                "type": "PirateHandler",
                "agent_card": {
                    "name": "Pirate Agent",
                    "description": "Speaks like a pirate"
                }
            },
            "math_agent": {
                "type": "MathHandler"
                # No agent_card section - should use defaults
            }
        }

        cards = get_agent_cards(handlers_config, "http://localhost:8000")

        # Should create cards for handler configs, not metadata
        assert len(cards) == 3
        assert "weather_agent" in cards
        assert "pirate_agent" in cards
        assert "math_agent" in cards

        # Metadata should be excluded
        assert "use_discovery" not in cards
        assert "handler_packages" not in cards
        assert "default_handler" not in cards

        # Verify specific cards
        assert cards["weather_agent"].name == "Weather Agent"
        assert cards["weather_agent"].description == "Provides weather information"
        
        assert cards["pirate_agent"].name == "Pirate Agent"
        assert cards["pirate_agent"].description == "Speaks like a pirate"
        
        assert cards["math_agent"].name == "Math Agent"  # Default formatting
        assert cards["math_agent"].description == "A2A handler for math_agent"

    def test_get_agent_cards_with_empty_config(self):
        """Test getting agent cards with empty handlers config."""
        handlers_config = {
            "use_discovery": False,
            "default_handler": "none"
        }

        cards = get_agent_cards(handlers_config, "http://localhost:8000")
        assert len(cards) == 0

    def test_get_agent_cards_skips_non_dict_values(self):
        """Test that non-dictionary handler configs are skipped."""
        handlers_config = {
            "valid_handler": {
                "type": "ValidHandler"
            },
            "string_value": "not_a_dict",
            "list_value": ["also", "not", "a", "dict"],
            "none_value": None,
            "use_discovery": False
        }

        cards = get_agent_cards(handlers_config, "http://localhost:8000")

        # Should only create card for valid handler
        assert len(cards) == 1
        assert "valid_handler" in cards
        assert "string_value" not in cards
        assert "list_value" not in cards
        assert "none_value" not in cards

    @patch('a2a_server.agent_card.logger')
    def test_get_agent_cards_handles_creation_errors(self, mock_logger):
        """Test that agent card creation errors are logged and handled gracefully."""
        handlers_config = {
            "good_handler": {
                "type": "GoodHandler"
            },
            "bad_handler": {
                "type": "BadHandler",
                "agent_card": {
                    "invalid_field": "causes_error"
                }
            }
        }

        # Mock create_agent_card to raise exception for bad_handler
        original_create = create_agent_card
        def mock_create_agent_card(handler_name, base_url, handler_cfg):
            if handler_name == "bad_handler":
                raise ValueError("Invalid configuration")
            return original_create(handler_name, base_url, handler_cfg)

        with patch('a2a_server.agent_card.create_agent_card', side_effect=mock_create_agent_card):
            cards = get_agent_cards(handlers_config, "http://localhost:8000")

            # Should create card for good handler, skip bad one
            assert len(cards) == 1
            assert "good_handler" in cards
            assert "bad_handler" not in cards

            # Should log error
            mock_logger.error.assert_called_once()
            error_call = mock_logger.error.call_args[0]
            # The actual log message uses %s formatting
            assert "Failed to create card for %s" in error_call[0]
            assert "bad_handler" in error_call[1]


class TestAgentCardEdgeCases:
    """Test edge cases and error conditions."""

    def test_create_agent_card_with_none_agent_card_section(self):
        """Test creating agent card when agent_card section is None."""
        handler_config = {
            "type": "TestHandler",
            "agent_card": None
        }

        # Should handle None gracefully by treating it as empty dict
        card = create_agent_card(
            handler_name="test_agent",
            base_url="http://localhost:8000",
            handler_cfg=handler_config
        )

        assert card.name == "Test Agent"
        assert card.description == "A2A handler for test_agent"

    def test_create_agent_card_with_empty_base_url(self):
        """Test creating agent card with empty base URL."""
        handler_config = {"type": "TestHandler"}

        card = create_agent_card(
            handler_name="test_agent",
            base_url="",
            handler_cfg=handler_config
        )

        # Should handle empty base URL
        assert card.url == "/test_agent"

    def test_create_agent_card_with_special_characters_in_name(self):
        """Test creating agent card with special characters in handler name."""
        handler_config = {"type": "TestHandler"}

        card = create_agent_card(
            handler_name="special-agent_with.chars",
            base_url="http://localhost:8000",
            handler_cfg=handler_config
        )

        # Should format name properly (only underscores are replaced with spaces and title-cased)
        assert card.name == "Special-Agent With.Chars"  # title() affects the whole string
        assert card.url == "http://localhost:8000/special-agent_with.chars"

    def test_create_agent_card_preserves_skill_order(self):
        """Test that skills maintain their order from configuration."""
        handler_config = {
            "agent_card": {
                "skills": [
                    {"id": "skill-3", "name": "Third Skill", "description": "Third"},
                    {"id": "skill-1", "name": "First Skill", "description": "First"},
                    {"id": "skill-2", "name": "Second Skill", "description": "Second"},
                ]
            }
        }

        card = create_agent_card(
            handler_name="ordered_agent",
            base_url="http://localhost:8000",
            handler_cfg=handler_config
        )

        # Skills should maintain configuration order
        assert len(card.skills) == 3
        assert card.skills[0].id == "skill-3"
        assert card.skills[1].id == "skill-1"
        assert card.skills[2].id == "skill-2"


class TestAgentCardSerialization:
    """Test agent card serialization and model compliance."""

    def test_agent_card_model_dump(self):
        """Test that agent cards can be serialized properly."""
        handler_config = {
            "agent_card": {
                "name": "Test Agent",
                "description": "A test agent",
                "version": "1.2.3",
                "documentationUrl": "https://docs.example.com",
                "capabilities": {
                    "streaming": True,
                    "pushNotifications": False
                },
                "skills": [
                    {
                        "id": "test-skill",
                        "name": "Test Skill",
                        "description": "A test skill",
                        "tags": ["test", "example"]
                    }
                ]
            }
        }

        card = create_agent_card(
            handler_name="test_agent",
            base_url="http://localhost:8000",
            handler_cfg=handler_config
        )

        # Test model_dump (Pydantic v2 style)
        if hasattr(card, 'model_dump'):
            card_dict = card.model_dump(exclude_none=True)
        else:
            # Fallback to dict() for older Pydantic versions
            card_dict = card.dict(exclude_none=True)

        # Verify serialization
        assert card_dict["name"] == "Test Agent"
        assert card_dict["description"] == "A test agent"
        assert card_dict["url"] == "http://localhost:8000/test_agent"
        assert card_dict["version"] == "1.2.3"
        # Check documentation URL field
        assert card_dict["documentation_url"] == "https://docs.example.com"

        # Capabilities should be nested properly
        assert card_dict["capabilities"]["streaming"] is True
        assert card_dict["capabilities"]["push_notifications"] is False
        assert card_dict["capabilities"]["state_transition_history"] is False

        # Skills should be serialized
        assert len(card_dict["skills"]) == 1
        assert card_dict["skills"][0]["id"] == "test-skill"
        assert card_dict["skills"][0]["tags"] == ["test", "example"]

    def test_agent_card_exclude_none_values(self):
        """Test that None values are properly excluded from serialization."""
        handler_config = {
            "agent_card": {
                "name": "Minimal Agent"
                # documentationUrl not specified (will be None)
            }
        }

        card = create_agent_card(
            handler_name="minimal_agent",
            base_url="http://localhost:8000",
            handler_cfg=handler_config
        )

        # Test serialization excludes None values
        if hasattr(card, 'model_dump'):
            card_dict = card.model_dump(exclude_none=True)
        else:
            card_dict = card.dict(exclude_none=True)

        # documentation_url should not be present if None
        assert "documentation_url" not in card_dict or card_dict["documentation_url"] is None
        assert card_dict["name"] == "Minimal Agent"


class TestIntegration:
    """Integration tests combining multiple features."""

    def test_realistic_agent_configuration(self):
        """Test with a realistic agent configuration."""
        handlers_config = {
            "use_discovery": True,
            "default_handler": "weather_agent",
            "weather_agent": {
                "type": "a2a_server.tasks.handlers.weather_handler.WeatherHandler",
                "agent": "weather_service",
                "agent_card": {
                    "name": "Weather Assistant",
                    "description": "Provides current weather conditions and forecasts",
                    "version": "2.1.0",
                    "documentationUrl": "https://weather-api.example.com/docs",
                    "capabilities": {
                        "streaming": True,
                        "pushNotifications": True,
                        "stateTransitionHistory": False
                    },
                    "defaultInputModes": ["text/plain"],
                    "defaultOutputModes": ["text/plain", "application/json"],
                    "skills": [
                        {
                            "id": "current-weather",
                            "name": "Current Weather",
                            "description": "Get current weather conditions for a location",
                            "tags": ["weather", "current", "conditions"],
                            "examples": [
                                "What's the weather like in London?",
                                "Current conditions in New York"
                            ]
                        },
                        {
                            "id": "weather-forecast",
                            "name": "Weather Forecast",
                            "description": "Get weather forecast for upcoming days",
                            "tags": ["weather", "forecast", "prediction"],
                            "examples": [
                                "5-day forecast for Paris",
                                "Will it rain tomorrow in Seattle?"
                            ]
                        }
                    ]
                }
            },
            "chat_agent": {
                "type": "a2a_server.tasks.handlers.chat_handler.ChatHandler",
                "agent": "general_chat"
                # No agent_card - should use defaults
            }
        }

        cards = get_agent_cards(handlers_config, "https://api.example.com")

        # Should create both cards
        assert len(cards) == 2
        
        weather_card = cards["weather_agent"]
        assert weather_card.name == "Weather Assistant"
        assert weather_card.version == "2.1.0"
        assert len(weather_card.skills) == 2
        assert weather_card.capabilities.push_notifications is True
        
        chat_card = cards["chat_agent"]
        assert chat_card.name == "Chat Agent"  # Default formatting
        assert chat_card.version == "1.0.0"  # Default version
        assert len(chat_card.skills) == 1  # Default skill


if __name__ == '__main__':
    pytest.main([__file__, '-v'])