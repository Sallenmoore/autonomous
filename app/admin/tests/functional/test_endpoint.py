import pytest
from src import create_app

import logging
log = logging.getLogger()

#################### TESTING ####################
class TestEndpoint: 

    @property
    def test_client(self):
        app = create_app()
        # Create a test client using the Flask application configured for testing
        with app.test_client() as testing_client:
            # Establish an application context
            with app.app_context():
                yield testing_client  # this is where the testing happens!
            
    def test_create(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        response = self.test_client.post('/create', json={})


    def test_all(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        response = self.test_client.post('/all', json={})
        
    def test_update(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        response = self.test_client.post('/update', json={})

    def test_get(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        response = self.test_client.post('/get', json={})

    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        response = self.test_client.post('/search', json={})
            
    def test_delete(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        response = self.test_client.post('/delete', json={})