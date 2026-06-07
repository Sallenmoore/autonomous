from .autoauth import AutoAuth
from .discord import DiscordAuth
from .facebook import FacebookAuth
from .github import GithubAuth
from .google import GoogleAuth
from .microsoft import MicrosoftAuth
from .user import AutoUser


auth_required = AutoAuth.auth_required
