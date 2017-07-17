# -*- mode: python; coding: utf-8 -*-
#
# Copyright (C) 2015 <contact@redhat.com>
#
# Author: Loic Dachary <loic@dachary.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see `<http://www.gnu.org/licenses/>`.
#
import git
import gitdb
import logging
import mock
import os
import pytest
import shutil
import tempfile

from github2gitlab import main

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s',
                    level=logging.DEBUG)


class TestGitHub2GitLab(object):

    def setup(self):
        self.gitlab_url = 'http://gitlab'
        self.gitlab_token = 'token'
        self.github_repo = 'user/repo'
        self.g = main.GitHub2GitLab.factory([
            '--verbose',
            '--gitlab-url', self.gitlab_url,
            '--gitlab-token', self.gitlab_token,
            '--github-repo', self.github_repo,
        ])
        self.d = tempfile.mkdtemp()

    def teardown(self):
        shutil.rmtree(self.d)

    def test_init(self):
        with pytest.raises(SystemExit):
            main.GitHub2GitLab.factory([])
        assert os.environ['HOME'] in self.g.args.ssh_public_key
        assert self.github_repo == self.g.github['repo']
        assert self.gitlab_url in self.g.gitlab['url']

    @mock.patch('requests.get')
    def test_get(self, m_requests_get):
        g = self.g

        class Request(object):
            def __init__(self, params):
                if params.get('page') == '1':
                    self.payload = [1]
                    self.headers = {}
                else:
                    self.payload = [0]
                    self.headers = {
                        "Link": ("<" + g.gitlab['url'] +
                                 '?page=1> rel="next"'),
                    }

            def json(self):
                return self.payload

        m_requests_get.side_effect = lambda url, params: Request(params)
        result = self.g.get(self.g.gitlab['url'], {'key': 'value'},
                            cache=False)
        assert m_requests_get.called
        assert [0, 1] == result
        other_result = self.g.get(self.g.gitlab['url'], {'key': 'value'},
                                  cache=False)
        assert result == other_result

    @mock.patch('requests.get')
    def test_get_pull_requests(self, m_requests_get):
        number1 = 1
        number2 = 2

        class Request(object):
            def __init__(self):
                self.headers = {}

            def json(self):
                return [{"number": number1},
                        {"number": number2}]

        m_requests_get.side_effect = lambda url, params: Request()
        result = self.g.get_pull_requests()
        assert {
            str(number1): {u'number': number1},
            str(number2): {u'number': number2},
        } == result

    @mock.patch('requests.get')
    def test_get_merge_requests(self, m_requests_get):
        id1 = 100
        id2 = 200

        class Request(object):
            def __init__(self):
                self.headers = {}

            def json(self):
                return [{"id": id1},
                        {"id": id2}]

        m_requests_get.side_effect = lambda url, params: Request()
        result = self.g.get_merge_requests()
        assert {
            str(id1): {u'id': id1},
            str(id2): {u'id': id2},
        } == result

    @mock.patch('requests.put')
    @mock.patch('requests.get')
    def test_unprotect_branches(self,
                                m_requests_get,
                                m_requests_put):
        class Get(object):
            def raise_for_status(self):
                pass

            def json(self):
                return [
                    {
                        'name': 'master',
                        'protected': True,
                    },
                    {
                        'name': 'branch1',
                        'protected': False,
                    },
                ]
        m_requests_get.side_effect = lambda url, params: Get()

        class Put(object):
            def raise_for_status(self):
                pass
        m_requests_put.side_effect = lambda url, params: Put()
        assert 1 == self.g.unprotect_branches()
        assert m_requests_get.called
        assert m_requests_put.called

    def test_update_merge_pull(self):
        id1 = '100'
        id2 = '200'
        number1 = '1'
        number2 = '2'
        self.g.pull_requests = {
            number1: {u'number': int(number1)},
            number2: {u'number': int(number2)},
        }
        self.g.merge_requests = {
            id1: {
                u'id': int(id1),
                u'source_branch': 'pull/' + number1 + '/head',
            },
            id2: {
                u'id': int(id2),
                u'source_branch': 'UNEXPECTED',
            },
        }
        self.g.update_merge_pull()
        assert self.g.merge2pull == {'100': {u'number': 1}}
        assert (self.g.pull2merge ==
                {'1': {u'id': 100, u'source_branch': 'pull/1/head'}})

    @mock.patch('requests.post')
    def test_create_merge_request(self, m_requests_post):
        data = {'title': u'TITLE é'}

        class Request(object):
            def __init__(self):
                self.status_code = 201

            def json(self):
                return data

        m_requests_post.side_effect = lambda url, params: Request()
        self.g.create_merge_request(data)
        assert m_requests_post.called

    @mock.patch('requests.post')
    def test_create_merge_request_fail(self, m_requests_post):
        data = {'title': u'TITLE é'}

        class Request(object):
            def __init__(self):
                self.status_code = 400
                self.text = 'FAIL'

        m_requests_post.side_effect = lambda *args, **kwargs: Request()
        with pytest.raises(ValueError):
            self.g.create_merge_request(data)
        assert m_requests_post.called

    @mock.patch('requests.put')
    def test_update_merge_request(self, m_requests_put):
        data = {
            'title': u'TITLE é',
            'state_event': 'close',
        }

        class Request(object):
            def json(self):
                data['state'] = 'closed'
                return data

        m_requests_put.side_effect = lambda url, params: Request()
        merge_request = {'id': 3}
        self.g.update_merge_request(merge_request, data)
        assert m_requests_put.called

    @mock.patch('requests.put')
    def test_update_merge_request_fail_state(self, m_requests_put):
        data = {'state_event': 'close'}

        class Request(object):
            def json(self):
                return {
                    'state': 'UNEXPECTED',
                    'iid': 1,
                    'merged': False,
                }

        m_requests_put.side_effect = lambda url, params: Request()
        merge_request = {'id': 3}
        with pytest.raises(ValueError) as e:
            self.g.update_merge_request(merge_request, data)
        assert 'UNEXPECTED' in str(e)
        assert m_requests_put.called

    @mock.patch('github2gitlab.main.GitHub2GitLab.put_merge_request')
    @mock.patch('github2gitlab.main.GitHub2GitLab.verify_merge_update')
    def test_update_merge_request_merge(self,
                                        m_verify_merge_update,
                                        m_put_merge_request):
        description = 'DESCRIPTION'

        def put(merge_request, updates):
            if updates['state_event'] == 'merge':
                updates['state'] = 'opened'
                updates['description'] = description
            else:
                updates['state'] = 'closed'
            return updates

        m_put_merge_request.side_effect = put
        merge_request = {'id': 3}
        result = self.g.update_merge_request(merge_request,
                                             {'state_event': 'merge'})
        assert self.g.TAG_MERGED in result['description']
        assert m_verify_merge_update.called

    @mock.patch('requests.get')
    @mock.patch('requests.post')
    def test_add_project_create(self,
                                m_requests_post,
                                m_requests_get):
        class Get(object):

            def __init__(self):
                self.status_code = 404
        m_requests_get.side_effect = lambda url, params: Get()

        class Post(object):
            def __init__(self):
                self.status_code = 201
                self.text = 'true'

            def json(self):
                return {}
        m_requests_post.side_effect = lambda url, params: Post()
        assert {} == self.g.add_project()
        assert m_requests_get.called
        assert m_requests_post.called

    @mock.patch('requests.get')
    @mock.patch('requests.post')
    def test_add_project_create_400(self,
                                    m_requests_post,
                                    m_requests_get):
        class Get(object):

            def __init__(self):
                self.status_code = 404
        m_requests_get.side_effect = lambda url, params: Get()
        error_message = 'ERROR MESSAGE'

        class Post(object):
            def __init__(self):
                self.status_code = 400
                self.text = error_message
        m_requests_post.side_effect = lambda url, params: Post()
        with pytest.raises(ValueError) as e:
            self.g.add_project()
        assert error_message in str(e)
        assert m_requests_get.called
        assert m_requests_post.called

    @mock.patch('requests.get')
    def test_add_project_noop(self, m_requests_get):
        class Get(object):
            def __init__(self):
                self.status_code = 200
        m_requests_get.side_effect = lambda url, params: Get()
        assert None == self.g.add_project()
        assert m_requests_get.called

    @mock.patch('requests.get')
    @mock.patch('requests.post')
    def test_add_key_create(self,
                            m_requests_post,
                            m_requests_get):
        public_key = 'PUBLIC KEY'
        ssh_public_key = self.d + "/key.pub"
        with open(ssh_public_key, 'w') as f:
            f.write(public_key)
        self.g.args.ssh_public_key = ssh_public_key

        class Get(object):
            def json(self):
                return []
        m_requests_get.side_effect = lambda url, params: Get()

        class Post(object):
            def __init__(self):
                self.status_code = 201
        m_requests_post.side_effect = lambda url, params: Post()
        assert public_key == self.g.add_key()
        assert m_requests_get.called
        assert m_requests_post.called

    @mock.patch('requests.get')
    @mock.patch('requests.post')
    def test_add_key_create_400(self,
                                m_requests_post,
                                m_requests_get):
        public_key = 'PUBLIC KEY'
        ssh_public_key = self.d + "/key.pub"
        with open(ssh_public_key, 'w') as f:
            f.write(public_key)
        self.g.args.ssh_public_key = ssh_public_key

        class Get(object):
            def json(self):
                return []
        m_requests_get.side_effect = lambda url, params: Get()
        error_message = 'ERROR MESSAGE'

        class Post(object):
            def __init__(self):
                self.status_code = 400
                self.text = error_message
        m_requests_post.side_effect = lambda url, params: Post()
        with pytest.raises(ValueError) as e:
            self.g.add_key()
        assert error_message in str(e)
        assert m_requests_get.called
        assert m_requests_post.called

    @mock.patch('requests.get')
    def test_add_key_noop(self, m_requests_get):
        public_key = 'PUBLIC KEY'
        ssh_public_key = self.d + "/key.pub"
        with open(ssh_public_key, 'w') as f:
            f.write(public_key)
        self.g.args.ssh_public_key = ssh_public_key

        class Get(object):
            def json(self):
                return [{'key': public_key}]
        m_requests_get.side_effect = lambda url, params: Get()
        assert None == self.g.add_key()
        assert m_requests_get.called

    @mock.patch('github2gitlab.main.GitHub2GitLab.update_merge_request')
    @mock.patch('github2gitlab.main.GitHub2GitLab.create_merge_request')
    @mock.patch('github2gitlab.main.GitHub2GitLab.rev_parse')
    def test_sync(self,
                  m_rev_parse,
                  m_create_merge_request,
                  m_update_merge_request):
        m_rev_parse.side_effect = lambda pull, revision: True
        self.g.pull_requests = {
            '1': {
                'number': 1,
                'state': 'open',
                'title': u'TITLE é',
                'body': 'DESCRIPTION è',
                'base': {
                    'ref': 'master',
                },
                'merged_at': None,
            },
            '2': {
                'number': 2,
                'state': 'closed',
                'title': 'OTHER_TITLE',
                'body': 'DESCRIPTION è',
                'merged_at': 'today',
            },
        }
        self.g.merge_requests = {
            '100': {
                'id': 100,
                'state': 'opened',
                'title': u'TITLE é',
                'description': 'DESCRIPTION è',
                'source_branch': 'pull/2/head',
                'target_branch': 'master',
            }
        }
        self.g.update_merge_pull()
        assert 1 == len(self.g.merge2pull)
        assert 2 == self.g.merge2pull['100']['number']
        assert 100 == self.g.pull2merge['2']['id']

        self.g.sync()
        m_update_merge_request.assert_called_with(
            self.g.merge_requests['100'],
            {
                'title': 'OTHER_TITLE',
                'state_event': 'merge',
            })
        pull = self.g.pull_requests['1']
        m_create_merge_request.assert_called_with({
            'title': pull['title'],
            'description': pull['body'],
            'target_branch': pull['base']['ref'],
            'source_branch': 'pull/' + str(pull['number']) + '/head',
        })

    @mock.patch('github2gitlab.main.GitHub2GitLab.gitlab_create_remote')
    def test_gitmirror(self, m_gitlab_create_remote):
        self.g.args.skip_pull_requests = True

        self.g.sh("""
        cd {dir}
        mkdir github
        cd github
        git init
        echo a > a ; git add a ; git commit -m "a" a
        """.format(dir=self.d))

        self.g.sh("""
        cd {dir}
        mkdir gitlab
        cd gitlab
        git init --bare
        """.format(dir=self.d))

        def gitlab_create_remote(repo):
            repo.create_remote('gitlab', self.d + "/gitlab")
        m_gitlab_create_remote.side_effect = gitlab_create_remote

        self.g.github['git'] = self.d
        self.g.github['repo'] = 'github'
        self.g.gitlab['name'] = 'project'

        cwd = os.getcwd()
        os.chdir(self.d)
        gitlab = git.Repo(self.d + '/gitlab')
        github = git.Repo(self.d + '/github')

        #
        # A pull request newly created only has pull/1/head
        # and will not be pushed to gitlab.
        #
        self.g.sh("""
        cd {dir}/github
        git branch pr-1
        git checkout pr-1
        echo 1 > 1 ; git add 1 ; git commit -m "1" 1
        git update-ref refs/pull/1/head HEAD
        git checkout master
        """.format(dir=self.d))

        self.g.git_mirror()

        with pytest.raises(gitdb.exc.BadName):
            gitlab.commit('pull/1/merge')

        #
        # After github successfully test a merge of a pull
        # request, the pull/1/merge reference exists and
        # it is pushed to gitlab
        #
        self.g.sh("""
        cd {dir}/github
        git branch pr-1-merge master
        git checkout pr-1-merge
        git merge --no-ff pr-1
        git update-ref refs/pull/1/merge HEAD
        git checkout master
        """.format(dir=self.d))

        self.g.git_mirror()
        assert gitlab.commit('pull/1/merge') == github.commit('pull/1/merge')

        #
        # When the base (master in this case) changes, github
        # may decide to re-try a merge. We ignore that because we're
        # only interested in pushing to gitlab when the head changes,
        # not every time the base changes and a merge is attempted.
        #
        self.g.sh("""
        cd {dir}/github
        git checkout master
        echo b > b ; git add b ; git commit -m "b" b
        git checkout pr-1-merge
        git reset --hard master
        git merge --no-ff pr-1
        git update-ref refs/pull/1/merge HEAD
        git checkout master
        """.format(dir=self.d))

        self.g.git_mirror()
        assert gitlab.commit('pull/1/merge') != github.commit('pull/1/merge')

        #
        # After a rebase and repush, pull/2/merge may reference the
        # previous pull/2/head and there is no point in pushing
        # it to gitlab: it would show an outdated state of the
        # pull request
        #
        self.g.sh("""
        cd {dir}/github
        # new pr
        git branch pr-2
        git checkout pr-2
        echo 2 > 2 ; git add 2 ; git commit -m "2" 2
        git update-ref refs/pull/2/head HEAD
        git checkout master
        # merge test
        git branch pr-2-merge master
        git checkout pr-2-merge
        git merge --no-ff pr-2
        git update-ref refs/pull/2/merge HEAD
        git checkout master
        # repush the pr
        git checkout pr-2
        echo 2.5 > 2.5 ; git add 2.5 ; git commit -m "2.5" 2.5
        git update-ref refs/pull/2/head HEAD
        git checkout master
        """.format(dir=self.d))

        self.g.git_mirror()
        with pytest.raises(gitdb.exc.BadName):
            gitlab.commit('pull/2/merge')

        #
        # After a rebase and repush, pull/3/merge is updated
        # if the merge check is successful.
        #
        self.g.sh("""
        cd {dir}/github
        # new pr
        git branch pr-3
        git checkout pr-3
        echo 3 > 3 ; git add 3 ; git commit -m "3" 3
        git update-ref refs/pull/3/head HEAD
        git checkout master
        # merge test
        git branch pr-3-merge master
        git checkout pr-3-merge
        git merge --no-ff pr-3
        git update-ref refs/pull/3/merge HEAD
        git checkout master
        """.format(dir=self.d))

        self.g.git_mirror()
        merge_1 = gitlab.commit('pull/3/merge')
        assert merge_1 == github.commit('pull/3/merge')

        self.g.sh("""
        cd {dir}/github
        # repush the pr
        git checkout pr-3
        echo 3.5 > 3.5 ; git add 3.5 ; git commit -m "3.5" 3.5
        git update-ref refs/pull/3/head HEAD
        git checkout master
        # re-verify merge
        git checkout pr-3-merge
        git reset --hard master
        git merge --no-ff pr-3
        git update-ref refs/pull/3/merge HEAD
        git checkout master
        """.format(dir=self.d))

        self.g.git_mirror()
        merge_2 = gitlab.commit('pull/3/merge')
        assert merge_1 != merge_2
        assert merge_2 == github.commit('pull/3/merge')

        #
        # All branches are pushed to gitlab by default
        #
        self.g.sh("""
        cd {dir}/github
        git branch b master
        git checkout b
        echo b > b ; git add b ; git commit -m "b" b
        git branch c master
        git checkout c
        echo c > c ; git add c ; git commit -m "c" c
        """.format(dir=self.d))

        self.g.git_mirror()
        assert gitlab.commit('b') == github.commit('b')
        assert gitlab.commit('c') == github.commit('c')

        #
        # If branches are given in argument, only those
        # are pushed to gitlab
        #
        self.g.sh("""
        cd {dir}/github
        git branch d master
        git checkout d
        echo d > d ; git add d ; git commit -m "d" d
        git branch e master
        git checkout e
        echo e > e ; git add e ; git commit -m "e" e
        git branch f master
        git checkout f
        echo f > f ; git add f ; git commit -m "f" f
        """.format(dir=self.d))

        self.g.github['branches'] = ['e', 'f']
        self.g.git_mirror()
        with pytest.raises(gitdb.exc.BadName):
            gitlab.commit('d')
        assert gitlab.commit('e') == github.commit('e')
        assert gitlab.commit('f') == github.commit('f')

        os.chdir(cwd)


class TestGitHub2GitLabNoSetup(object):

    def test_json_loads(self):
        r = main.GitHub2GitLab.json_loads('{}')
        assert {} == r
        with pytest.raises(ValueError):
            main.GitHub2GitLab.json_loads(']')

# Local Variables:
# compile-command: "../.tox/py27/bin/py.test test_github2gitlab.py"
# End:
