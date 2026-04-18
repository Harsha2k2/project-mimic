from project_mimic.testing.ephemeral_services import ephemeral_integration_environment
from project_mimic.vision.triton_client import TritonConfig, TritonVisionClient


def test_ephemeral_integration_environment_serves_triton_infer() -> None:
    with ephemeral_integration_environment() as env:
        client = TritonVisionClient(
            TritonConfig(
                endpoint=env.triton_endpoint,
                model_name="ui-detector",
                allowed_hosts=("127.0.0.1",),
            ),
        )

        entities = client.infer_entities(b"frame")
        assert len(entities) == 1
        assert entities[0].entity_id == "e1"
