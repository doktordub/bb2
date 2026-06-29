"""Fake implementations for contract-focused backend tests."""

from app.testing.fakes.fake_agent import FakeAgent
from app.testing.fakes.fake_clock import FakeClock
from app.testing.fakes.fake_config import FakeConfigurationLoader, FakeConfigurationView
from app.testing.fakes.fake_llm import FakeLLMGateway
from app.testing.fakes.fake_memory import FakeMemoryGateway
from app.testing.fakes.fake_orchestration_runtime import FakeOrchestrationRuntime
from app.testing.fakes.fake_policy import FakePolicyService
from app.testing.fakes.fake_session_service import FakeSessionService
from app.testing.fakes.fake_state import FakeWorkflowStateStore
from app.testing.fakes.fake_strategy import FakeDirectStrategy
from app.testing.fakes.fake_tools import FakeToolGateway
from app.testing.fakes.fake_trace import FakeTraceStore

__all__ = [
	"FakeAgent",
	"FakeClock",
	"FakeConfigurationLoader",
	"FakeConfigurationView",
	"FakeDirectStrategy",
	"FakeLLMGateway",
	"FakeMemoryGateway",
	"FakeOrchestrationRuntime",
	"FakePolicyService",
	"FakeSessionService",
	"FakeToolGateway",
	"FakeTraceStore",
	"FakeWorkflowStateStore",
]