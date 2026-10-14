from langchain_community.utilities.github import GitHubAPIWrapper

wrapper = GitHubAPIWrapper()
repo = wrapper.github_repo_instance