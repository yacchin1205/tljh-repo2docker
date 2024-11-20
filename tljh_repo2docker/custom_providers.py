from jupyterhub.utils import url_path_join
from .launcher import LaunchHandler

token_store_path = '/opt/tljh/state/repo2docker.sqlite'

def create_custom_build_handlers(service_prefix):
    from binderhub.repoproviders import (
        GitHubRepoProvider, GitRepoProvider, GitLabRepoProvider, GistRepoProvider,
        ZenodoProvider, FigshareProvider, HydroshareProvider, DataverseProvider,
        RDMProvider, WEKO3Provider,
    )

    repo_providers = {
        'gh': GitHubRepoProvider,
        'gist': GistRepoProvider,
        'git': GitRepoProvider,
        'gl': GitLabRepoProvider,
        'zenodo': ZenodoProvider,
        'figshare': FigshareProvider,
        'hydroshare': HydroshareProvider,
        'dataverse': DataverseProvider,
        'rdm': RDMProvider,
        'weko3': WEKO3Provider,
    }

    return [
        (
            url_path_join(service_prefix, r"hub/build/([^/]+)/[^/]+/[^/]+"),
            LaunchHandler,
            {
                "repo_providers": repo_providers,
                "token_store_path": token_store_path,
            },
        ),
    ]
