from .GHCallbacks import GHRemoteCallbacks

import pygit2
import shutil
import os

class Repository:

    def __init__(self, repo=None, path="./"):
        """
        _summary_

        Args:
            repo (_type_, optional): _description_. Defaults to None.
            path (str, optional): _description_. Defaults to "./".
        """
        self.dir = path
        self.path = f'{path}/{repo.name}'
        if not os.path.exists(self.path):
            self.repo = pygit2.clone_repository(repo.clone_url, self.path, callbacks=GHRemoteCallbacks())
        else:
            repository_path = pygit2.discover_repository(self.path)
            self.repo = pygit2.Repository(repository_path)
            self.pull()

    def copy_file(self, src, dest=None, overwrite=False):
        # f"{doc_dir}/client_update.md", dest=f"planning/sprints/sprint{sprint}"
        """
        copies file from a path to this repository in the given path

        Args:
            src (_type_): _description_
            dest (_type_, optional): _description_. Defaults to None.
            overwrite (bool, optional): _description_. Defaults to False.
        """
        dest_path = self.repo.path.replace(".git/", '')
        if overwrite or not os.path.isfile(f"{dest_path}{dest}"):
            for dir in dest.split('/')[:-1]:
                if not os.path.isdir(f"{dest_path}{dir}"):
                    os.mkdir(f"{dest_path}{dir}")
                dest_path = f"{dest_path}{dir}/"
            shutil.copyfile(src, f"{dest_path}{dest.split('/')[-1]}")

    def pull(self, remote_name='origin', branch='main'):
        """
        _summary_

        Args:
            remote_name (str, optional): _description_. Defaults to 'origin'.
            branch (str, optional): _description_. Defaults to 'main'.

        Raises:
            AssertionError: _description_
            AssertionError: _description_
        """
        for remote in self.repo.remotes:
            remote.fetch(callbacks=GHRemoteCallbacks())
            remote_master_id = self.repo.lookup_reference(f'refs/remotes/origin/{branch}').target
            merge_result, _ = self.repo.merge_analysis(remote_master_id)
            # Up to date, do nothing
            if merge_result & pygit2.GIT_MERGE_ANALYSIS_UP_TO_DATE:
                return
            # We can just fastforward
            elif merge_result & pygit2.GIT_MERGE_ANALYSIS_FASTFORWARD:
                self.repo.checkout_tree(self.repo.get(remote_master_id))
                try:
                    master_ref = self.repo.lookup_reference(f'refs/heads/{branch}')
                    master_ref.set_target(remote_master_id)
                except KeyError:
                    self.repo.create_branch(branch, self.repo.get(remote_master_id))
                    self.repo.head.set_target(remote_master_id)
            elif merge_result & pygit2.GIT_MERGE_ANALYSIS_NORMAL:
                self.repo.merge(remote_master_id)

                if self.repo.index.conflicts is not None:
                    for conflict in self.repo.index.conflicts:
                        print(f'Conflicts found in: {conflict[0].path}')
                    raise AssertionError('Conflicts, ahhhhh!!')
                user = self.repo.default_signature
                tree = self.repo.index.write_tree()
                target = [self.repo.head.target, remote_master_id]
                self.repo.create_commit('HEAD', user, user, 'Merge!', tree, target)
                # We need to do this or git CLI will think we are still merging.
                self.repo.state_cleanup()
            else:
                raise AssertionError('Unknown merge analysis result')

    def commit(self):
        """
        _summary_
        """
        ref = self.repo.head.name
        parents = [self.repo.head.target]
        index = self.repo.index
        index.add_all()
        index.write()
        author = pygit2.Signature('Steven Moore', 'samoore@binghamton.edu')
        committer = author
        message = "updates from prof"
        tree = index.write_tree()
        self.repo.create_commit(ref, author, committer, message, tree, parents)
        
    def push(self, remote_name='origin', ref=None):
        """
        _summary_

        Args:
            remote_name (str, optional): _description_. Defaults to 'origin'.
            ref (str, optional): _description_. Defaults to 'refs/heads/master:refs/heads/master'.
        """
        if not ref:
            ref = ['refs/heads/main:refs/heads/main']
        for remote in self.repo.remotes:
            remote.push(ref, callbacks=GHRemoteCallbacks())
