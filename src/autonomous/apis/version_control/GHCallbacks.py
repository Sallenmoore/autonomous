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

        # NOTE (#256): do NOT add a ``certificate_check`` override here.
        # This class previously defined one that returned a bare ``True``,
        # which tells libgit2 to accept ANY certificate from ANY host — on
        # the same object whose ``credentials()`` above hands a GITHUB_PAT
        # to that peer. Inheriting ``pygit2.RemoteCallbacks``'s version
        # (it raises ``Passthrough``) defers to libgit2's own validation,
        # which GitHub's real certificates satisfy. If a self-signed
        # remote ever genuinely needs a bypass, make it an explicit,
        # loudly-logged opt-in — never the default, and never unconditional.
