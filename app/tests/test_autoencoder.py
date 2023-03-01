from autolib import log
from autolib.autoencoder import AutoEncoder


class TestAutoencoder:
    def test_autoencoder_get_class(self):
        klass = AutoEncoder.get_class(
            "tests.autoencoder.test_autoencoder", "TestAutoencoder"
        )
        assert isinstance(klass, TestAutoencoder)

    def test_autoencoder_default(self):
        pass

    def _serialize_autoencoder_get_class(self):
        pass

    def _deserialize_autoencoder_get_class(self):
        pass

    def deserialize_autoencoder_get_class(self):
        pass
