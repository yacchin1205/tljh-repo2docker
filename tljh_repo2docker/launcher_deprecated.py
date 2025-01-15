import json
import re
from aiodocker import Docker, DockerError
from jupyterhub.handlers.base import BaseHandler
from tornado import web
from .docker import build_image
from .token import TokenStore

class LaunchRedirectHandler(BaseHandler):
    """
    Handle requests from GRDM to build user environments as Docker images
    """

    @web.authenticated
    async def get(self, provider_prefix):
        query = self.request.query
        if len(query) > 0:
            query = f'?{query}'
        self.redirect(f'/services/tljh_repo2docker{self.request.path}{query}')
