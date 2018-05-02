#!/usr/bin/env python

from ansible.module_utils.basic import AnsibleModule
import json

import urllib2


DOCUMENTATION = '''
---
module: wf_source
short_description:
    - Enables interfacing with the Wavefront API to create a source and tags
requirements: []
author:
    - Wavefront
    - Mike McMahon
'''

EXAMPLES = '''

# Create/update a source with the specified tags/description
wf_source:
    token: WAVEFRONT_TOKEN
    endpoint: https://WAVEFRONT_CLUSTER.wavefront.com
    source: SOURCE_NAME_IN_WAVEFRONT
    description: "primary app server for try cluster"
    tags:
        - prod

# Hide a source
wf_source:
    token: WAVEFRONT_TOKEN
    endpoint: https://WAVEFRONT_CLUSTER.wavefront.com
    source: SOURCE_NAME_IN_WAVEFRONT
    hidden: True

    # If tags or description are specified they will update the source
    # Otherwise we don't touch these as part of hiding a source
'''

CREATE_SOURCE_ENDPOINT = '/api/v2/source'
MANAGE_SOURCE_ENDPOINT = '/api/v2/source/{}'


class RequestWithMethod(urllib2.Request):
    """
    Allow us to override the default method being used
    """

    def __init__(self, *args, **kwargs):
        """
        Override and init the new request method
        :param args:
        :param kwargs:
        """
        self._method = kwargs.pop('method', None)
        urllib2.Request.__init__(self, *args, **kwargs)

    def get_method(self):
        return self._method if self._method else \
            urllib2.Request.get_method(self)


def _read_response(response):
    try:
        return json.loads(response)
    except ValueError:
        return {}


def get_existing_source(module, source, token, endpoint):
    """
    Queries to see if the specified source exists
    :param module:
    :param source:
    :param token:
    :param endpoint:
    :return:
    """
    api_endpoint = '{}{}'.format(endpoint, MANAGE_SOURCE_ENDPOINT.format(
        source
    ))
    request = RequestWithMethod(api_endpoint, method='GET')
    request.add_header('Authorization', 'Bearer {}'.format(token))
    try:
        response = urllib2.urlopen(request)
    except urllib2.HTTPError as url_error:
        body = _read_response(url_error.read())
        if body:
            message = body.get('status', {}).get('message', '')
            if message and 'does not exist' in message:
                return {}
        module.fail_json(
            msg='Unable to query endpoint for source {}\n{}'.format(
                source,
                body
            )
        )
    else:
        return json.loads(response.read())


def create_source(module, source, tags, description, token, endpoint):
    """
    Creates a given source
    :param module:
    :param source:
    :param tags:
    :param description:
    :param token:
    :param endpoint:
    :return:
    """
    api_endpoint = '{}{}'.format(endpoint, CREATE_SOURCE_ENDPOINT)
    payload = {
        'sourceName': source,
        'tags': dict(zip(tags, [True]*len(tags))),
        'description': description
    }

    request = RequestWithMethod(
        api_endpoint,
        data=json.dumps(payload).encode('utf-8'),
        method='POST'
    )
    request.add_header('Authorization', 'Bearer {}'.format(token))
    request.add_header('Content-Type', 'application/json')

    try:
        response = urllib2.urlopen(request)
    except urllib2.HTTPError as url_error:
        body = _read_response(url_error.read())
        if body:
            message = body.get('status', {}).get('message', '')
            if message and 'already exists' in message:
                return True
        else:
            module.fail_json(
                msg='There was an error talking to the '
                    'server on {} endpoint \n{}'.format(
                        api_endpoint,
                        url_error
                    ))
    else:
        try:
            return payload
        except ValueError:
            module.fail_json(
                msg='There was an issue processing the response from the server'
            )


def update_source(module, source, tags, description, token, endpoint, hidden=False):
    """
    Updates a given source with the newly provided tags/description
    :param module:
    :param source:
    :param token:
    :param endpoint:
    :return:
    """
    api_endpoint = '{}{}'.format(endpoint, MANAGE_SOURCE_ENDPOINT.format(
        source
    ))
    payload = {
        'sourceName': source,
        'tags': dict(zip(tags, [True]*len(tags))),
        'description': description
    }

    if hidden:
        tags = payload['tags']
        tags['hidden'] = True
        payload['tags'] = tags

    request = RequestWithMethod(
        api_endpoint,
        data=json.dumps(payload).encode('utf-8'),
        method='PUT'
    )
    request.add_header('Content-Type', 'application/json')

    request.add_header('Authorization', 'Bearer {}'.format(token))
    try:
        response = urllib2.urlopen(request)
    except urllib2.HTTPError as url_error:
        body = _read_response(url_error.read())
        if body:
            message = body.get('status', {}).get('message', '')
            if message and 'does not exist' in message:
                return {}

        module.fail_json(
            msg='Unable to query {} for source {}'.format(
                api_endpoint,
                source
            ),
            payload=payload,
            exception=str(url_error)
        )
    else:
        return payload


def main():
    module = AnsibleModule(argument_spec=dict(
        token=dict(required=True, default=None),
        endpoint=dict(default=None),
        source=dict(required=True, default=None),
        hidden=dict(default=False, type='bool'),
        description=dict(default=''),
        tags=dict(default=[], type='list')
    ))

    params = module.params
    token = params['token']
    endpoint = params['endpoint']
    source = params['source']
    hidden = params['hidden']
    description = params['description']
    tags = params['tags']

    existing_source = get_existing_source(module, source, token, endpoint)

    # Right now it will always look changed, but i'm not sure that matters
    if existing_source:
        payload = update_source(module, source, tags, description,
                      token, endpoint, hidden)
        changed = True
    else:
        payload = create_source(module, source, tags, description,
                      token, endpoint)
        changed = True

    existing_source = get_existing_source(module, source, token, endpoint)
    module.exit_json(
        changed=changed,
        source=existing_source.get('response'),
        payload=payload
    )

if __name__ == '__main__':
    main()
