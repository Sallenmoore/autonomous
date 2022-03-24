from src import create_app
import pytest

@pytest.fixture(scope='module')
def test_client():
    app = create_app()
    # Create a test client using the Flask application configured for testing
    with app.test_client() as testing_client:
        # Establish an application context
        with app.app_context():
            yield testing_client  # this is where the testing happens!

@pytest.fixture(scope='module')
def test_search_terms():

    return {}

@pytest.fixture(scope='module')
def test_search_term():

    return ""