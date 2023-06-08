import pygit2
import os

class GHRemoteCallbacks(pygit2.RemoteCallbacks):
        def __init__(self):
            """
            _summary_
            """
            self.user = os.environ.get('GITHUB_USERNAME')
            self.token = os.environ.get('GITHUB_PAT')
            
        def credentials(self, url, username_from_url, allowed_types):
            """
            _summary_

            Args:
                url (_type_): _description_
                username_from_url (_type_): _description_
                allowed_types (_type_): _description_

            Returns:
                _type_: _description_
            """
            return pygit2.UserPass(self.user,self.token)
        
        def certificate_check(self, certificate, valid, host):
            """
            _summary_

            Args:
                certificate (_type_): _description_
                valid (_type_): _description_
                host (_type_): _description_

            Returns:
                _type_: _description_
            """
            return True
