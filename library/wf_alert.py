#!/usr/bin/env python

import json
import urllib2

from ansible.module_utils.basic import AnsibleModule

DOCUMENTATION = '''
---
module: wf_alert
short_description:
    - Enables interfacing with reading wf alerts
requirements: []
author:
    - Wavefront
    - Mike McMahon
'''

EXAMPLES = '''

# Read the output of an alert as it is in WF
wf_alert:
    token: WAVEFRONT_TOKEN
    endpoint: https://WAVEFRONT_CLUSTER.wavefront.com
    alert_id: ALERT_ID_IN_WAVEFRONT
'''

WF_ALERT_API = "/api/v2/alert/{}"


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


def get_alert(ansible_module, token, endpoint, alert_id):
    """
    gets the wavefront alert and formats into something usable by ansible
    :param token:
    :param endpoint:
    :param alert_id:
    :return:
    """
    api_endpoint = '{}{}'.format(endpoint, WF_ALERT_API.format(
        alert_id
    ))
    request = RequestWithMethod(
        api_endpoint,
        method='GET'
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

            ansible_module.fail_json(
                msg='Unable to query {} for alert_id {}'.format(
                    api_endpoint,
                    alert_id
                ),
                exception=str(url_error)
            )
    else:
        return _read_response(response.read())


def main():
    ansible_module = AnsibleModule(argument_spec=dict(
        token=dict(required=True, default=None),
        endpoint=dict(default=None),
        alert_id=dict(required=True, default=None),
    ))

    params = ansible_module.params
    token = params['token']
    endpoint = params['endpoint']
    alert_id = params['alert_id']

    alert_details = get_alert(ansible_module, token, endpoint, alert_id)

    ansible_module.exit_json(
        changed=False,
        alert=alert_details.get('response', {})
    )

if __name__ == '__main__':
    main()
