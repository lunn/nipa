# SPDX-License-Identifier: GPL-2.0
#
# Copyright (C) 2019 Netronome Systems, Inc.

try:
    import simplejson as json
except ImportError:
    import json
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import urllib

import core

# TODO: document


class PatchworkCheckState:
    SUCCESS = "success",
    WARNING = "warning",
    FAIL = "fail"


class PatchworkPostException(Exception):
    pass


class Patchwork(object):
    def __init__(self, config):
        self._session = requests.Session()
        retry = Retry(connect=10, backoff_factor=1)
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount('http://', adapter)
        self._session.mount('https://', adapter)

        self.server = config.get('patchwork', 'server')
        ssl = config.getboolean('patchwork', 'use_ssl', fallback=True)
        self._proto = "https://" if ssl else "http://"
        self._token = config.get('patchwork', 'token', fallback='')
        self._user = config.get('patchwork', 'user', fallback='')

        config_project = config.get('patchwork', 'project')
        pw_project = self.get_project(config_project)
        if pw_project:
            self._project = pw_project['id']
        else:
            try:
                self._project = int(config_project)
            except ValueError:
                raise Exception("Patchwork project not found", config_project)

    def _request(self, url):
        try:
            core.log_open_sec(f"Patchwork {self.server} request: {url}")
            ret = self._session.get(url)
            core.log("Response", ret)
            try:
                core.log("Response data", ret.json())
            except json.decoder.JSONDecodeError:
                core.log("Response data", ret.content.decode())
        finally:
            core.log_end_sec()

        return ret

    def request(self, url):
        return self._request(url).json()

    def get(self, object_type, identifier):
        return self._get(f'{object_type}/{identifier}/').json()

    def get_all(self, object_type, filters=None, api='1.1'):
        if filters is None:
            filters = {}
        params = ''
        for key, val in filters.items():
            if val is not None:
                params += f'{key}={val}&'

        items = []

        response = self._get(f'{object_type}/?{params}', api=api)
        # Handle paging, by chasing the "Link" elements
        while response:
            for o in response.json():
                items.append(o)

            if 'Link' not in response.headers:
                break

            # There are multiple links separated by commas
            links = response.headers['Link'].split(',')
            # And each link has the format of <url>; rel="type"
            response = None
            for link in links:
                info = link.split(';')
                if info[1].strip() == 'rel="next"':
                    response = self._request(info[0][1:-1])

        return items

    def get_by_msgid(self, object_type, msgid):
        msgid = urllib.parse.quote(msgid)
        return self._get(f'{object_type}/?msgid={msgid}&project={self._project}', api='').json()

    def get_mbox(self, object_type, identifier):
        url = f'{self._proto}{self.server}/{object_type}/{identifier}/mbox/'
        return self._request(url).content.decode()

    def _get(self, req, api='1.1'):
        if api:
            api += "/"
        return self._request(f'{self._proto}{self.server}/api/{api}{req}')

    def _post(self, req, headers, data, api='1.1'):
        url = f'{self._proto}{self.server}/api/{api}/{req}'
        try:
            core.log_open_sec(f"Patchwork {self.server} post: {url}")
            ret = self._session.post(url, headers=headers, data=data)
            core.log("Headers", headers)
            core.log("Data", data)
            core.log("Response", ret)
            core.log("Response data", ret.json())
        finally:
            core.log_end_sec()

        return ret

    # PATCH as in the HTTP method, not getting a patch
    def _patch(self, req, headers, data, api='1.1'):
        url = f'{self._proto}{self.server}/api/{api}/{req}'
        try:
            core.log_open_sec(f"Patchwork {self.server} post: {url}")
            ret = self._session.patch(url, headers=headers, data=data)
            core.log("Headers", headers)
            core.log("Data", data)
            core.log("Response", ret)
            core.log("Response data", ret.json())
        finally:
            core.log_end_sec()

        return ret

    def get_project(self, name):
        all_projects = self.get_projects_all()
        for project in all_projects:
            if project['name'] == name:
                return project

    def get_projects_all(self):
        return self.get_all('projects')

    def get_patches_all(self, delegate=None, project=None, since=None):
        if project is None:
            project = self._project
        query = {'project': project }
        if delegate:
            query['delegate'] = delegate
        if since:
            query['since'] = since
        return self.get_all('patches', query)

    def get_series_all(self, project=None, since=None):
        if project is None:
            project = self._project
        return self.get_all('series', {'project': project, 'since': since})

    def post_check(self, patch, name, state, url, desc):
        headers = {}
        if self._token:
            headers['Authorization'] = f'Token {self._token}'

        data = {
            'user': self._user,
            'state': state,
            'target_url': url,
            'context': name,
            'description': desc
        }

        r = self._post(f'patches/{patch}/checks/', headers=headers, data=data)
        if r.status_code != 201:
            raise PatchworkPostException(r)

    def update_state(self, patch, state):
        headers = {}
        if self._token:
            headers['Authorization'] = f'Token {self._token}'

        data = {
            'state': state
        }

        r = self._patch(f'patches/{patch}/', headers=headers, data=data)
        if r.status_code != 200:
            raise PatchworkPostException(r)
