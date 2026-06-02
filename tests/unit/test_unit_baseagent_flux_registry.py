"""FluxAIModel must be registered in BaseAgent.MODEL_REGISTRY under the
'flux' key so ImageAgent's routing layer can dispatch to it via the
existing get_client mechanism."""

from autonomous.ai.baseagent import BaseAgent
from autonomous.ai.models.flux import FluxAIModel


def test_flux_registered_in_model_registry():
    assert BaseAgent.MODEL_REGISTRY.get("flux") is FluxAIModel
