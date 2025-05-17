# """
# Tests for the agent_card module.
# """
# import pytest
# from a2a_server.agent_card import (
#     create_agent_card,
#     get_agent_cards,
#     AgentCard,
#     Capabilities,
#     Authentication,
#     Skill
# )

# @pytest.fixture
# def sample_handler_config():
#     """Provide a sample handler configuration with agent_card section."""
#     return {
#         "type": "a2a_server.tasks.handlers.google_adk_handler.GoogleADKHandler",
#         "agent": "a2a_server.sample_agents.pirate_agent.pirate_agent",
#         "name": "pirate_agent",
#         "agent_card": {
#             "name": "Pirate Agent",
#             "description": "Converts your text into salty pirate-speak",
#             "version": "0.1.0",
#             "documentationUrl": "https://pirate.example.com/docs",
#             "provider": {
#                 "organization": "Acme",
#                 "url": "https://acme.example.com"
#             },
#             "capabilities": {
#                 "streaming": True,
#                 "pushNotifications": False
#             },
#             "authentication": {
#                 "schemes": ["None"]
#             },
#             "defaultInputModes": ["text/plain"],
#             "defaultOutputModes": ["text/plain"],
#             "skills": [
#                 {
#                     "id": "pirate-talk",
#                     "name": "Pirate Talk",
#                     "description": "Turn any message into pirate lingo",
#                     "tags": ["pirate", "fun"],
#                     "examples": ["Arrr! Give me yer loot!"]
#                 }
#             ]
#         }
#     }

# @pytest.fixture
# def minimal_handler_config():
#     """Provide a minimal handler configuration without agent_card section."""
#     return {
#         "type": "a2a_server.tasks.handlers.google_adk_handler.GoogleADKHandler",
#         "agent": "a2a_server.sample_agents.pirate_agent.pirate_agent",
#         "name": "minimal_agent"
#     }

# @pytest.fixture
# def handlers_config(sample_handler_config, minimal_handler_config):
#     """Provide a sample handlers configuration section."""
#     return {
#         "use_discovery": False,
#         "default": "pirate_agent",
#         "handler_packages": [],
#         "pirate_agent": sample_handler_config,
#         "minimal_agent": minimal_handler_config
#     }

# def test_create_agent_card_with_full_config(sample_handler_config):
#     """Test creating an agent card with a full configuration."""
#     card = create_agent_card(
#         handler_name="pirate_agent",
#         base_url="http://localhost:8000",
#         handler_config=sample_handler_config
#     )
    
#     assert card.name == "Pirate Agent"
#     assert card.description == "Converts your text into salty pirate-speak"
#     assert card.url == "http://localhost:8000/pirate_agent"
#     assert card.version == "0.1.0"
#     assert card.documentationUrl == "https://pirate.example.com/docs"
    
#     assert card.provider is not None
#     assert card.provider.organization == "Acme"
#     assert card.provider.url == "https://acme.example.com"
    
#     assert card.capabilities.streaming is True
#     assert card.capabilities.pushNotifications is False
#     assert card.capabilities.stateTransitionHistory is False
    
#     assert card.authentication.schemes == ["None"]
#     assert card.defaultInputModes == ["text/plain"]
#     assert card.defaultOutputModes == ["text/plain"]
    
#     assert len(card.skills) == 1
#     assert card.skills[0].id == "pirate-talk"
#     assert card.skills[0].name == "Pirate Talk"
#     assert card.skills[0].description == "Turn any message into pirate lingo"
#     assert card.skills[0].tags == ["pirate", "fun"]
#     assert card.skills[0].examples == ["Arrr! Give me yer loot!"]

# def test_create_agent_card_with_minimal_config(minimal_handler_config):
#     """Test creating an agent card with minimal configuration."""
#     card = create_agent_card(
#         handler_name="minimal_agent",
#         base_url="http://localhost:8000",
#         handler_config=minimal_handler_config
#     )
    
#     # Check that defaults were applied
#     assert card.name == "Minimal Agent"  # Title-cased and spaces added
#     assert card.description == "A2A handler for minimal_agent"
#     assert card.url == "http://localhost:8000/minimal_agent"
#     assert card.version == "1.0.0"  # Default version
    
#     # Default capabilities
#     assert card.capabilities.streaming is True
#     assert card.capabilities.pushNotifications is False
#     assert card.capabilities.stateTransitionHistory is False
    
#     # Default authentication
#     assert card.authentication.schemes == ["None"]
    
#     # Default content types
#     assert card.defaultInputModes == ["text/plain"]
#     assert card.defaultOutputModes == ["text/plain"]
    
#     # Default skill
#     assert len(card.skills) == 1
#     assert card.skills[0].id == "minimal_agent-default"
#     assert card.skills[0].name == "Minimal Agent"
#     assert card.skills[0].description == "Default capability for minimal_agent"
#     assert card.skills[0].tags == ["minimal_agent"]
#     assert card.skills[0].examples == []

# def test_create_agent_card_with_custom_url():
#     """Test creating an agent card with a custom URL in the configuration."""
#     config = {
#         "agent_card": {
#             "url": "https://custom-url.example.com"
#         }
#     }
    
#     card = create_agent_card(
#         handler_name="custom_url_agent",
#         base_url="http://localhost:8000",
#         handler_config=config
#     )
    
#     # The custom URL should be used instead of the base_url
#     assert card.url == "https://custom-url.example.com"

# def test_get_agent_cards(handlers_config):
#     """Test getting agent cards for all handlers."""
#     cards = get_agent_cards(
#         handlers_config=handlers_config,
#         base_url="http://localhost:8000"
#     )
    
#     # Should have cards for both handlers
#     assert len(cards) == 2
#     assert "pirate_agent" in cards
#     assert "minimal_agent" in cards
    
#     # Check that the pirate_agent card has the expected name
#     assert cards["pirate_agent"].name == "Pirate Agent"
    
#     # Check that the minimal_agent card has the default name
#     assert cards["minimal_agent"].name == "Minimal Agent"
    
#     # Metadata keys should be skipped
#     assert "use_discovery" not in cards
#     assert "default" not in cards
#     assert "handler_packages" not in cards

# def test_agent_card_serialization():
#     """Test that agent cards can be properly serialized to JSON."""
#     card = AgentCard(
#         name="Test Agent",
#         description="A test agent",
#         url="http://test.example.com",
#         version="1.0.0",
#         capabilities=Capabilities(
#             streaming=True,
#             pushNotifications=False,
#             stateTransitionHistory=False
#         ),
#         authentication=Authentication(
#             schemes=["None"]
#         ),
#         defaultInputModes=["text/plain"],
#         defaultOutputModes=["text/plain"],
#         skills=[
#             Skill(
#                 id="test-skill",
#                 name="Test Skill",
#                 description="A test skill",
#                 tags=["test"]
#             )
#         ]
#     )
    
#     # Test serialization using dict()
#     card_dict = card.dict(exclude_none=True)
#     assert card_dict["name"] == "Test Agent"
#     assert card_dict["description"] == "A test agent"
#     assert card_dict["url"] == "http://test.example.com"
#     assert card_dict["capabilities"]["streaming"] is True
    
#     # None values should be excluded
#     assert "documentationUrl" not in card_dict
#     assert "provider" not in card_dict
    
#     # Test nested serialization
#     assert "examples" not in card_dict["skills"][0]
    
# def test_agent_card_missing_required_fields():
#     """Test that agent cards require certain fields."""
#     # Missing required fields should raise an error
#     with pytest.raises(ValueError):
#         AgentCard(
#             name="Test Agent",
#             # Missing description
#             url="http://test.example.com",
#             version="1.0.0",
#             capabilities=Capabilities(),
#             authentication=Authentication(schemes=["None"]),
#             defaultInputModes=["text/plain"],
#             defaultOutputModes=["text/plain"],
#             skills=[]
#         )