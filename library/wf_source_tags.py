#!/usr/bin/env python

from time import sleep

from ansible.module_utils.basic import AnsibleModule
import json
import math

import urllib2


DOCUMENTATION = '''
---
module: wf_source_tags
short_description:
    - Enables interfacing with the Wavefront API to configure source tags
requirements: []
author:
    - Wavefront
    - Mike McMahon
'''

EXAMPLES = '''

# Remove the prod tag from a source
wf_source_tags:
    token: WAVEFRONT_TOKEN
    endpoint: hhttps://WAVEFRONT_CLUSTER.wavefront.com
    source: SOURCE_NAME_IN_WAVEFRONT
    state: absent
    tags:
        - prod

# Add retired tag to a source
wf_source_tags:
    token: WAVEFRONT_TOKEN
    endpoint: https://WAVEFRONT_CLUSTER.wavefront.com
    source: try-2a-app15-i-0a04798b7fef872c9
    state: present
    tags:
        - retired

# Get all tags for a source
wf_source_tags:
    token: WAVEFRONT_TOKEN
    endpoint: https://WAVEFRONT_CLUSTER.wavefront.com
    source: SOURCE_NAME_IN_WAVEFRONT
register: source_tags

debug:
  var: source_tags.tags

# Replace tags for a given source with new tags
wf_source_tags:
    token: WAVEFRONT_TOKEN
    endpoint: https://WAVEFRONT_CLUSTER.wavefront.com
    source: SOURCE_NAME_IN_WAVEFRONT
    state: replace
    tags:
        - prod
        - dc-3
        - closet-14
        - rack-21
        - webserver
        - nginx
'''

GET_TAGS_ENDPOINT = '/api/v2/source/{}/tag'
PUT_TAGS_ENDPOINT = '/api/v2/source/{}/tag/{}'
DELETE_TAGS_ENDPOINT = '/api/v2/source/{}/tag/{}'


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


def get_existing_tags(module, source, token, endpoint):
    """
    Queries the source and gets the current tags assigned to said source
    :param module:
    :param source:
    :param token:
    :param endpoint:
    :return:
    """
    api_endpoint = '{}{}'.format(endpoint, GET_TAGS_ENDPOINT.format(source))
    request = RequestWithMethod(api_endpoint, method='GET')
    request.add_header('Authorization', 'Bearer {}'.format(token))

    try:
        response = urllib2.urlopen(request)
    except urllib2.URLError as url_error:
        module.fail_json(
            msg='There was an error talking to the '
                'server on {} endpoint \n{}'.format(
                    api_endpoint,
                    url_error
            )
        )
    except urllib2.HTTPError as http_error:
        module.fail_json(
            msg='Failed to query the endpoint for the specified resource'
        )
        return False

    try:
        body = json.loads(response.read())
        tags = body.get('response', {}).get('items', [])
        return tags
    except ValueError:
        module.fail_json(
            msg='There was an issue processing the response from the server'
        )
        return False


def put_tag(module, source, tag_value, token, endpoint):
    """
    puts a given tag onto the specified source
    :param module:
    :param source:
    :param tag_value:
    :param token:
    :param endpoint:
    :return:
    """
    api_endpoint = '{}{}'.format(
        endpoint,
        PUT_TAGS_ENDPOINT.format(
            source,
            tag_value
        )
    )
    request = RequestWithMethod(api_endpoint, method='PUT')
    request.add_header('Authorization', 'Bearer {}'.format(token))

    attempts = 1
    while True:
        try:
            response = urllib2.urlopen(request)
            return True
        except urllib2.HTTPError as http_error:
            if attempts == 10:
                module.fail_json(
                    msg='Failed to put the tag {} onto the source {}'.format(
                        tag_value,
                        source
                    )
                )
                return False
            else:
                # having issues sleep for a bit, soft backoff.
                sleep_time = 2 * math.sqrt(attempts)
                sleep(sleep_time)
                attempts += 1


def delete_tag(module, source, tag_value, token, endpoint):
    """
    Removes a given tag from the specified source
    :param module:
    :param source:
    :param tag_value:
    :param token:
    :param endpoint:
    :return:
    """
    api_endpoint = '{}{}'.format(
        endpoint,
        DELETE_TAGS_ENDPOINT.format(
            source,
            tag_value
        )
    )
    request = RequestWithMethod(api_endpoint, method='DELETE')
    request.add_header('Authorization', 'Bearer {}'.format(token))

    try:
        response = urllib2.urlopen(request)
    except urllib2.HTTPError as http_error:
        module.fail_json(
            msg='Failed to delete the tag {} from the source {}'.format(
                tag_value,
                source
            )
        )
        return False

    return True


def main():
    module = AnsibleModule(argument_spec=dict(
        token=dict(required=True, default=None),
        endpoint=dict(default='https://mon.wavefront.com'),
        source=dict(required=True, default=None),
        state=dict(default=None, choices=['absent', 'present', 'replace']),
        tags=dict(default=None, type='list')
    ))

    params = module.params
    token = params['token']
    endpoint = params['endpoint']
    source = params['source']
    state = params['state']
    tags = params['tags']

    existing_tags = get_existing_tags(module, source, token, endpoint)
    changed = False

    if tags:
        # Make sure these are removed
        if state == 'absent':
            for tag in tags:
                if tag in existing_tags:
                    delete_tag(module, source, tag, token, endpoint)
                    changed = True

        if state == 'present':
            for tag in tags:
                if tag not in existing_tags:
                    put_tag(module, source, tag, token, endpoint)
                    changed = True

        if state == 'replace':
            for tag in existing_tags:
                # Remove the tags that are existing but not specified
                if tag not in tags:
                    delete_tag(module, source, tag, token, endpoint)
                    changed = True

            for tag in tags:
                # if the new tag doesn't exist yet we should create it
                if tag not in existing_tags:
                    put_tag(module, source, tag, token, endpoint)
                    changed = True

        # Get refreshed tag list
        existing_tags = get_existing_tags(module, source, token, endpoint)
        module.exit_json(changed=changed, tags=existing_tags)

    elif not tags:
        module.exit_json(changed=changed, tags=existing_tags)

    module.fail_json(
        msg='There was an issue with the module'
    )

if __name__ == '__main__':
    main()
