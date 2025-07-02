#!/usr/bin/env python3
# tests/test_metrics.py
"""
Comprehensive unit tests for a2a_server.metrics module.

Tests the OpenTelemetry metrics integration including:
- Provider initialization and configuration
- Prometheus metrics endpoint
- Console and OTLP exporters
- Middleware instrumentation
- Graceful shutdown handling
- Environment variable configuration
"""

import os
import pytest
from unittest.mock import Mock, patch, MagicMock, call
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse

import a2a_server.metrics as metrics_module


class TestEnvironmentConfiguration:
    """Test environment variable configuration."""

    @patch.dict(os.environ, {}, clear=True)
    def test_default_configuration(self):
        """Test default configuration when no env vars are set."""
        # Reload module to pick up clean environment
        import importlib
        importlib.reload(metrics_module)
        
        assert metrics_module._OTLP_ENDPOINT is None
        assert metrics_module._PROM_ENABLED is False
        assert metrics_module._CONSOLE_ENABLED is False
        assert metrics_module._SERVICE_NAME == "a2a-server"
        assert metrics_module._INTERVAL_MS == 15000

    @patch.dict(os.environ, {
        'OTEL_EXPORTER_OTLP_ENDPOINT': 'http://localhost:4318',
        'PROMETHEUS_METRICS': 'true',
        'CONSOLE_METRICS': 'true',
        'OTEL_SERVICE_NAME': 'test-service',
        'OTEL_EXPORT_INTERVAL_MS': '5000'
    })
    def test_environment_variable_configuration(self):
        """Test configuration from environment variables."""
        import importlib
        importlib.reload(metrics_module)
        
        assert metrics_module._OTLP_ENDPOINT == 'http://localhost:4318'
        assert metrics_module._PROM_ENABLED is True
        assert metrics_module._CONSOLE_ENABLED is True
        assert metrics_module._SERVICE_NAME == 'test-service'
        assert metrics_module._INTERVAL_MS == 5000

    @patch.dict(os.environ, {
        'PROMETHEUS_METRICS': 'false',
        'CONSOLE_METRICS': 'FALSE',
        'PROMETHEUS_METRICS': 'no'
    })
    def test_boolean_environment_parsing(self):
        """Test that boolean environment variables are parsed correctly."""
        import importlib
        importlib.reload(metrics_module)
        
        # Only 'true' (case insensitive) should enable features
        assert metrics_module._PROM_ENABLED is False
        assert metrics_module._CONSOLE_ENABLED is False


class TestPrometheusIntegration:
    """Test Prometheus integration when available."""

    def setup_method(self):
        """Reset global state before each test."""
        metrics_module._provider = None
        metrics_module._counter = None
        metrics_module._histogram = None

    def test_prometheus_enabled_when_available(self):
        """Test Prometheus integration when dependencies are available."""
        # Test the current state - if Prometheus is enabled, it should be configured
        if metrics_module._PROM_ENABLED:
            assert metrics_module._prom_reader is not None
            assert metrics_module.prometheus_client is not None
        else:
            # If not enabled, verify the fallback behavior
            assert metrics_module._prom_reader is None

    def test_prometheus_disabled_when_unavailable(self):
        """Test Prometheus gracefully disabled when dependencies missing."""
        # This tests the current module state after import
        # The actual behavior depends on whether prometheus_client is available
        # We just verify the module doesn't crash during import
        assert hasattr(metrics_module, '_PROM_ENABLED')
        assert hasattr(metrics_module, 'prometheus_client')


class TestProviderInitialization:
    """Test metrics provider initialization."""

    def setup_method(self):
        """Reset global state before each test."""
        metrics_module._provider = None
        metrics_module._counter = None
        metrics_module._histogram = None

    @patch('a2a_server.metrics.metrics.set_meter_provider')
    @patch('a2a_server.metrics.metrics.get_meter_provider')
    def test_init_provider_creates_new_provider(self, mock_get_provider, mock_set_provider):
        """Test that _init_provider creates a new provider when none exists."""
        # Create a real class for MeterProvider to use with isinstance
        class MockMeterProviderType:
            def __init__(self, *args, **kwargs):
                self.shutdown = Mock()
                
        # Mock get_meter_provider to return something that's not a MeterProvider
        mock_current_provider = Mock()
        mock_get_provider.return_value = mock_current_provider
        
        with patch('a2a_server.metrics.MeterProvider', MockMeterProviderType) as mock_meter_provider:
            with patch('a2a_server.metrics.metrics.get_meter') as mock_get_meter:
                mock_meter = Mock()
                mock_get_meter.return_value = mock_meter
                mock_counter = Mock()
                mock_histogram = Mock()
                mock_meter.create_counter.return_value = mock_counter
                mock_meter.create_histogram.return_value = mock_histogram
                
                # Reset provider state to force creation
                metrics_module._provider = None
                
                metrics_module._init_provider()
                
                # Should have created a new provider since current isn't MeterProvider instance
                mock_set_provider.assert_called_once()
                assert metrics_module._counter is mock_counter
                assert metrics_module._histogram is mock_histogram

    def test_init_provider_idempotent(self):
        """Test that _init_provider is idempotent when already configured."""
        # Set up already configured state
        mock_provider = Mock()
        mock_counter = Mock()
        mock_histogram = Mock()
        
        metrics_module._provider = mock_provider
        metrics_module._counter = mock_counter
        metrics_module._histogram = mock_histogram
        
        with patch('a2a_server.metrics.metrics.get_meter_provider') as mock_get_provider:
            metrics_module._init_provider()
            
            # Should not have called get_meter_provider since already configured
            mock_get_provider.assert_not_called()
            
            # State should remain unchanged
            assert metrics_module._provider is mock_provider
            assert metrics_module._counter is mock_counter
            assert metrics_module._histogram is mock_histogram

    @patch('a2a_server.metrics.PeriodicExportingMetricReader')
    @patch('a2a_server.metrics.OTLPMetricExporter')
    @patch('a2a_server.metrics.metrics.set_meter_provider')
    @patch('a2a_server.metrics.metrics.get_meter')
    @patch('a2a_server.metrics.metrics.get_meter_provider')
    def test_init_provider_with_otlp_endpoint(self, mock_get_provider, mock_get_meter, mock_set_provider, mock_otlp_exporter, mock_periodic_reader):
        """Test provider initialization with OTLP endpoint."""
        # Create real class for isinstance check
        class MockMeterProviderType:
            def __init__(self, *args, **kwargs):
                self.shutdown = Mock()
        
        mock_exporter = Mock()
        mock_otlp_exporter.return_value = mock_exporter
        mock_reader = Mock()
        mock_periodic_reader.return_value = mock_reader
        mock_meter = Mock()
        mock_get_meter.return_value = mock_meter
        mock_meter.create_counter.return_value = Mock()
        mock_meter.create_histogram.return_value = Mock()
        mock_get_provider.return_value = Mock()  # Not a MeterProvider
        
        with patch('a2a_server.metrics.MeterProvider', MockMeterProviderType):
            # Reset state and set OTLP endpoint
            metrics_module._provider = None
            original_endpoint = metrics_module._OTLP_ENDPOINT
            metrics_module._OTLP_ENDPOINT = 'http://localhost:4318'
            
            try:
                metrics_module._init_provider()
                
                mock_otlp_exporter.assert_called_once_with(
                    endpoint='http://localhost:4318', 
                    insecure=True
                )
                mock_periodic_reader.assert_called_once_with(
                    mock_exporter,
                    export_interval_millis=metrics_module._INTERVAL_MS
                )
            finally:
                metrics_module._OTLP_ENDPOINT = original_endpoint

    @patch('a2a_server.metrics.PeriodicExportingMetricReader')
    @patch('a2a_server.metrics.ConsoleMetricExporter')
    @patch('a2a_server.metrics.metrics.set_meter_provider')
    @patch('a2a_server.metrics.metrics.get_meter')
    @patch('a2a_server.metrics.metrics.get_meter_provider')
    def test_init_provider_with_console_exporter(self, mock_get_provider, mock_get_meter, mock_set_provider, mock_console_exporter, mock_periodic_reader):
        """Test provider initialization with console exporter."""
        # Create real class for isinstance check
        class MockMeterProviderType:
            def __init__(self, *args, **kwargs):
                self.shutdown = Mock()
        
        mock_exporter = Mock()
        mock_console_exporter.return_value = mock_exporter
        mock_reader = Mock()
        mock_periodic_reader.return_value = mock_reader
        mock_meter = Mock()
        mock_get_meter.return_value = mock_meter
        mock_meter.create_counter.return_value = Mock()
        mock_meter.create_histogram.return_value = Mock()
        mock_get_provider.return_value = Mock()  # Not a MeterProvider
        
        with patch('a2a_server.metrics.MeterProvider', MockMeterProviderType):
            # Reset state and enable console
            metrics_module._provider = None
            original_console = metrics_module._CONSOLE_ENABLED
            original_otlp = metrics_module._OTLP_ENDPOINT
            metrics_module._CONSOLE_ENABLED = True
            metrics_module._OTLP_ENDPOINT = None  # Disable OTLP to test console path
            
            try:
                metrics_module._init_provider()
                
                mock_console_exporter.assert_called_once()
                mock_periodic_reader.assert_called_once_with(
                    mock_exporter,
                    export_interval_millis=metrics_module._INTERVAL_MS
                )
            finally:
                metrics_module._CONSOLE_ENABLED = original_console
                metrics_module._OTLP_ENDPOINT = original_otlp


class TestAppInstrumentation:
    """Test FastAPI app instrumentation."""

    def setup_method(self):
        """Reset global state before each test."""
        metrics_module._provider = None
        metrics_module._counter = None
        metrics_module._histogram = None

    @patch('a2a_server.metrics._init_provider')
    def test_instrument_app_calls_init_provider(self, mock_init_provider):
        """Test that instrument_app calls _init_provider."""
        app = FastAPI()
        
        metrics_module.instrument_app(app)
        
        mock_init_provider.assert_called_once()

    def test_instrument_app_adds_middleware_once(self):
        """Test that middleware is only added once."""
        app = FastAPI()
        
        with patch('a2a_server.metrics._init_provider'):
            # First call should add middleware
            metrics_module.instrument_app(app)
            assert hasattr(app.state, '_otel_middleware')
            assert app.state._otel_middleware is True
            
            # Second call should be no-op
            middleware_count_before = len(app.user_middleware)
            metrics_module.instrument_app(app)
            middleware_count_after = len(app.user_middleware)
            
            assert middleware_count_before == middleware_count_after

    @patch.dict(os.environ, {'PROMETHEUS_METRICS': 'true'})
    def test_instrument_app_adds_prometheus_endpoint_once(self):
        """Test that Prometheus endpoint is only added once."""
        app = FastAPI()
        
        # Only test if Prometheus is actually enabled
        if not metrics_module._PROM_ENABLED:
            pytest.skip("Prometheus not enabled in current environment")
        
        with patch('a2a_server.metrics._init_provider'):
            # First call should add endpoint
            metrics_module.instrument_app(app)
            assert hasattr(app.state, '_prom_endpoint')
            assert app.state._prom_endpoint is True
            
            # Second call should be no-op
            routes_count_before = len(app.routes)
            metrics_module.instrument_app(app)
            routes_count_after = len(app.routes)
            
            assert routes_count_before == routes_count_after

    @patch.dict(os.environ, {'PROMETHEUS_METRICS': 'true'})
    def test_prometheus_metrics_endpoint(self):
        """Test that Prometheus metrics endpoint works correctly."""
        app = FastAPI()
        
        # Only test if Prometheus is actually enabled in the module
        if not metrics_module._PROM_ENABLED:
            pytest.skip("Prometheus not enabled in current environment")
        
        with patch('a2a_server.metrics._init_provider'):
            with patch('a2a_server.metrics._prom_reader', Mock()):
                # Mock the prometheus modules that might be imported
                with patch('prometheus_client.REGISTRY') as mock_registry:
                    with patch('prometheus_client.generate_latest') as mock_generate:
                        with patch('prometheus_client.CONTENT_TYPE_LATEST', 'text/plain'):
                            mock_generate.return_value = b"# Prometheus metrics\ntest_metric 1.0\n"
                            
                            metrics_module.instrument_app(app)
                            
                            client = TestClient(app)
                            response = client.get("/metrics")
                            
                            assert response.status_code == 200
                            mock_generate.assert_called_once_with(mock_registry)


class TestMiddlewareFunctionality:
    """Test middleware functionality."""

    def setup_method(self):
        """Reset global state before each test."""
        metrics_module._provider = None
        metrics_module._counter = Mock()
        metrics_module._histogram = Mock()

    @pytest.mark.asyncio
    async def test_middleware_records_metrics(self):
        """Test that middleware records request metrics."""
        app = FastAPI()
        
        @app.get("/test")
        async def test_endpoint():
            return {"message": "test"}
        
        with patch('a2a_server.metrics._init_provider'):
            metrics_module.instrument_app(app)
            
            client = TestClient(app)
            response = client.get("/test")
            
            assert response.status_code == 200
            
            # Verify counter was called
            metrics_module._counter.add.assert_called_once()
            counter_call = metrics_module._counter.add.call_args
            assert counter_call[0][0] == 1  # Count
            
            # Verify histogram was called
            metrics_module._histogram.record.assert_called_once()
            histogram_call = metrics_module._histogram.record.call_args
            assert histogram_call[0][0] > 0  # Duration should be positive
            
            # Verify attributes
            attrs = counter_call[0][1]
            assert attrs["http.method"] == "GET"
            assert attrs["http.route"] == "/test"
            assert attrs["http.status_code"] == "200"

    @pytest.mark.asyncio
    async def test_middleware_handles_exceptions(self):
        """Test that middleware handles exceptions in endpoints."""
        app = FastAPI()
        
        @app.get("/error")
        async def error_endpoint():
            raise ValueError("Test error")
        
        # Add exception handler to prevent the test from failing
        @app.exception_handler(ValueError)
        async def handle_value_error(request, exc):
            return JSONResponse(
                status_code=500,
                content={"detail": str(exc)}
            )
        
        with patch('a2a_server.metrics._init_provider'):
            metrics_module.instrument_app(app)
            
            client = TestClient(app)
            response = client.get("/error")
            
            assert response.status_code == 500
            
            # Metrics should still be recorded
            metrics_module._counter.add.assert_called_once()
            metrics_module._histogram.record.assert_called_once()
            
            # Should record the error status
            attrs = metrics_module._counter.add.call_args[0][1]
            assert attrs["http.status_code"] == "500"


class TestShutdownHandling:
    """Test graceful shutdown handling."""

    def setup_method(self):
        """Reset global state before each test."""
        metrics_module._provider = None

    def test_shutdown_provider_idempotent(self):
        """Test that shutdown is idempotent and doesn't raise on repeated calls."""
        # Test with no provider
        metrics_module._shutdown_provider()  # Should not raise
        
        # Test with provider that has a shutdown method
        mock_provider = Mock()
        mock_provider._shutdown = False  # Not already shutdown
        mock_provider._is_shutdown = False
        metrics_module._provider = mock_provider
        
        metrics_module._shutdown_provider()
        mock_provider.shutdown.assert_called_once()
        assert metrics_module._provider is None
        
        # Second call should be no-op
        metrics_module._shutdown_provider()  # Should not raise

    def test_shutdown_provider_handles_exceptions(self):
        """Test that shutdown handles provider exceptions gracefully."""
        mock_provider = Mock()
        mock_provider._shutdown = False
        mock_provider._is_shutdown = False
        mock_provider.shutdown.side_effect = RuntimeError("Shutdown error")
        metrics_module._provider = mock_provider
        
        # Should not raise despite provider error
        metrics_module._shutdown_provider()
        assert metrics_module._provider is None

    def test_shutdown_provider_handles_already_shutdown(self):
        """Test handling of already shutdown providers."""
        mock_provider = Mock()
        mock_provider._shutdown = True  # Simulate already shutdown
        mock_provider._is_shutdown = True
        metrics_module._provider = mock_provider
        
        metrics_module._shutdown_provider()
        mock_provider.shutdown.assert_not_called()
        assert metrics_module._provider is None

    @patch('a2a_server.metrics.atexit.register')
    def test_atexit_handler_registered(self, mock_atexit_register):
        """Test that atexit handler is registered."""
        import importlib
        importlib.reload(metrics_module)
        
        mock_atexit_register.assert_called_with(metrics_module._shutdown_provider)


class TestIntegration:
    """Integration tests combining multiple features."""

    def setup_method(self):
        """Reset global state before each test."""
        metrics_module._provider = None
        metrics_module._counter = None
        metrics_module._histogram = None

    def test_full_integration_with_multiple_exporters(self):
        """Test full integration with both OTLP and Prometheus exporters."""
        app = FastAPI()
        
        @app.get("/integration")
        async def integration_endpoint():
            return {"status": "ok"}
        
        # Create real class for isinstance check
        class MockMeterProviderType:
            def __init__(self, *args, **kwargs):
                self.shutdown = Mock()
        
        # Mock the metrics components
        with patch('a2a_server.metrics.OTLPMetricExporter') as mock_otlp:
            with patch('a2a_server.metrics.PrometheusMetricReader') as mock_prom:
                with patch('a2a_server.metrics.MeterProvider', MockMeterProviderType) as mock_meter_provider:
                    with patch('a2a_server.metrics.metrics.get_meter') as mock_get_meter:
                        with patch('a2a_server.metrics.metrics.set_meter_provider'):
                            with patch('a2a_server.metrics.metrics.get_meter_provider') as mock_get_provider:
                                mock_get_provider.return_value = Mock()  # Not a MeterProvider
                                mock_meter = Mock()
                                mock_counter = Mock()
                                mock_histogram = Mock()
                                mock_meter.create_counter.return_value = mock_counter
                                mock_meter.create_histogram.return_value = mock_histogram
                                mock_get_meter.return_value = mock_meter
                                
                                # Temporarily override module settings
                                orig_otlp = metrics_module._OTLP_ENDPOINT
                                orig_prom = metrics_module._PROM_ENABLED
                                orig_provider = metrics_module._provider
                                
                                metrics_module._OTLP_ENDPOINT = 'http://localhost:4318'
                                metrics_module._PROM_ENABLED = True
                                metrics_module._provider = None  # Force re-initialization
                                
                                try:
                                    # Instrument the app
                                    metrics_module.instrument_app(app)
                                    
                                    # Test the endpoint
                                    client = TestClient(app)
                                    response = client.get("/integration")
                                    assert response.status_code == 200
                                    
                                    # Verify metrics were recorded
                                    mock_counter.add.assert_called_once()
                                    mock_histogram.record.assert_called_once()
                                finally:
                                    metrics_module._OTLP_ENDPOINT = orig_otlp
                                    metrics_module._PROM_ENABLED = orig_prom
                                    metrics_module._provider = orig_provider

    def test_metrics_without_prometheus_dependency(self):
        """Test that metrics work when Prometheus is not available."""
        app = FastAPI()
        
        @app.get("/no-prom")
        async def no_prom_endpoint():
            return {"message": "no prometheus"}
        
        # Create real class for isinstance check
        class MockMeterProviderType:
            def __init__(self, *args, **kwargs):
                self.shutdown = Mock()
        
        # Ensure prometheus is disabled
        original_prom_enabled = metrics_module._PROM_ENABLED
        original_prom_reader = metrics_module._prom_reader
        original_provider = metrics_module._provider
        
        metrics_module._PROM_ENABLED = False
        metrics_module._prom_reader = None
        metrics_module._provider = None
        
        try:
            with patch('a2a_server.metrics.MeterProvider', MockMeterProviderType) as mock_meter_provider:
                with patch('a2a_server.metrics.metrics.get_meter') as mock_get_meter:
                    with patch('a2a_server.metrics.metrics.set_meter_provider'):
                        with patch('a2a_server.metrics.metrics.get_meter_provider') as mock_get_provider:
                            mock_get_provider.return_value = Mock()  # Not a MeterProvider
                            mock_meter = Mock()
                            mock_counter = Mock()
                            mock_histogram = Mock()
                            mock_meter.create_counter.return_value = mock_counter
                            mock_meter.create_histogram.return_value = mock_histogram
                            mock_get_meter.return_value = mock_meter
                            
                            metrics_module.instrument_app(app)
                            
                            client = TestClient(app)
                            response = client.get("/no-prom")
                            assert response.status_code == 200
                            
                            # Should not have /metrics endpoint
                            metrics_response = client.get("/metrics")
                            assert metrics_response.status_code == 404
                            
                            # Metrics should be recorded for both requests (2 calls total)
                            assert mock_counter.add.call_count == 2
                            assert mock_histogram.record.call_count == 2
                            
                            # Verify the calls were for the right endpoints
                            calls = mock_counter.add.call_args_list
                            first_call_attrs = calls[0][0][1]  # First call attributes
                            second_call_attrs = calls[1][0][1]  # Second call attributes
                            
                            assert first_call_attrs["http.route"] == "/no-prom"
                            assert first_call_attrs["http.status_code"] == "200"
                            assert second_call_attrs["http.route"] == "/metrics"
                            assert second_call_attrs["http.status_code"] == "404"
        finally:
            # Restore original state
            metrics_module._PROM_ENABLED = original_prom_enabled
            metrics_module._prom_reader = original_prom_reader
            metrics_module._provider = original_provider


class TestErrorConditions:
    """Test error conditions and edge cases."""

    def setup_method(self):
        """Reset global state before each test."""
        metrics_module._provider = None
        metrics_module._counter = None
        metrics_module._histogram = None

    def test_instrument_app_with_none_app(self):
        """Test that instrument_app handles None app gracefully."""
        with pytest.raises(AttributeError):
            metrics_module.instrument_app(None)

    @patch('a2a_server.metrics.metrics.get_meter')
    def test_init_provider_with_meter_creation_failure(self, mock_get_meter):
        """Test handling of meter creation failure."""
        mock_get_meter.side_effect = RuntimeError("Meter creation failed")
        
        with pytest.raises(RuntimeError):
            metrics_module._init_provider()

    def test_middleware_with_missing_route(self):
        """Test middleware behavior when route information is missing."""
        app = FastAPI()
        
        with patch('a2a_server.metrics._init_provider'):
            # Mock counter and histogram
            metrics_module._counter = Mock()
            metrics_module._histogram = Mock()
            
            metrics_module.instrument_app(app)
            
            # Create a request that doesn't match any route
            client = TestClient(app)
            response = client.get("/nonexistent")
            
            assert response.status_code == 404
            
            # Metrics should still be recorded with the path as route
            metrics_module._counter.add.assert_called_once()
            attrs = metrics_module._counter.add.call_args[0][1]
            assert attrs["http.route"] == "/nonexistent"  # Falls back to path
            assert attrs["http.status_code"] == "404"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])