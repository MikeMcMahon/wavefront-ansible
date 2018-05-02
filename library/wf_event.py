# (C) 2017-2018, VMware, Inc. All Rights Reserved.
# SPDX-License-Identifier: GPL-3.0
# (C) 2017 Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# Make coding more python3-ish
from __future__ import (absolute_import, division, print_function)

__metaclass__ = type

import ast
from copy import deepcopy
import datetime
import json
import urllib2
import time

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.six import iteritems

ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'vmware'}

DOCUMENTATION = '''
---
module: wf_event
short_description:
    - Create, read and update wavefront events
description:
    - Create, read and update wavefront events
    - Install <ansible_playbook_home>/filter_plugins/timedelta.py for jinja plugins
    - to_epoch_millis, timedelta to easily create timestamps relative to ansible_date_time 
version_added: "2.4.5"
options:
    endpoint:
      description:
         - Wavefront base url example.wavefront.com
      required: true
    token:
      description:
         - Wavefront api_key token
      required: true
    name:
      description: 
        - event name.  Required if using wf_event as a POST
      required: false
    query:
      description:
        - a list of dict of query filters to find the event(s)
        - query item dict has keys "key", "value", "matchingMethod"
        - matchingMethod in ['CONTAINS', 'STARTSWITH', 'EQUALS']
    hosts:
      description:
        - list of hosts the event applies to
    start_time:
      description: start time of event in epoch milliseconds
      default: "datetime.utcnow() - timedelta(hours=-1) converted to epoch milliseconds"
    end_time:
      description: end time of event in epoch milliseconds
      default: "datetime.utcnow() converted to epoch milliseconds"
    id:
      description: 
        - id of wavefront event.  Required for POST.  Format is "<epoch timestamp millis>:<event_name>"
    body:
      description: 
        - dict to POST as body for the alert of form VALID_EVENT_DICT.  
        - Using 'body' requires 'id'.
        - If id and body are given, assume an update
        - updatable fields are ['annotations', 'endTime', 'hosts', 'name', 'startTime', 'table', 'tags']
        - startTime/endTime in body over-rides start_time/end_time in wf_event args for updates.
      default: None
    delete:
      description: 
        - if True and id is given, delete (body, query ignored)
      default: 'False'
    limit:
      description:
        - nax number of results to return
      default: 10
              
requirements: []
author:
    - Wavefront
    - Kesten Broughton
'''

EXAMPLES = '''

# Get events matching query in timewindow using name via search api
wf_event:
  endpoint: example.wavefront.com
  token: 123456789-1234-1a11-aa11-123456789abcd
  query:
    [ {key: "hosts", value: "cluster1", matchingMethod: "CONTAINS"},
      {key: "name", value: "ERROR", matchingMethod: "STARTSWITH"} ]
  start_time: "datetime.datetime(2017, 1, 1)"
  end_time: "datetime.timedelta(days=-1)"

# Get an event using id via event api
wf_event:
  endpoint:
  id: 1507307331000: CPU is > 90%
        
# Update an event giving it an end_time in epoch millis. (you have to find the id with a wf_event GET)
wf_event:
  endpoint: https://example.wavefront.com
  id: 1507307331000: CPU is > 90%
  end_time:  1507307334999

# Post and event
wf_event:
  endpoint:
  starttime:
  endtime:
  hosts:
   - some set of hosts
  annotations: { free_form: yes, dict: yes, limit: "more than a hundred a day can cause performance issues" }

Post an event with body only.  Size limit 10k.  Put free form debugrmation in annotations dict.
wf_event:
  id: "1507307331000: My new event"
  body: { dict defined at '{{ endpoint }}/api-docs/ui/#!/Event/getAllEventsWithTimeRange' }

'''

MAX_ATTEMPTS = 1

VALID_EVENT_DICT = {
    "name": str,
    "annotations": dict,
    "id": str,
    "table": str,
    "startTime": int,
    "endTime": int,
    "tags": list,
    "createdAt": int,
    "hosts": list,
    "isEphemeral": bool,
    "creatorId": str,
    "createdEpochMillis": int,
    "updatedEpochMillis": int,
    "updaterId": str,
    "updatedAt": int,
    "summarizedEvents": int,
    "isUserEvent": bool,
    "runningState": str,
    "canClose": bool,
    "creatorType": list,
    "canDelete": bool
}

def safe_cast(key, val):
    if key in ['name', 'id', 'table', 'creatorId', 'updaterId', 'runningState']:
        return str(val)
    elif key == 'annotations':
        return dict(val)
    elif key in ['tags', 'creatorType', 'hosts']:
        return list(val)
    elif key in ['startTime', 'endTime', 'createdAt', 'createdEpochMillis',
                 'updatedEpochMillis', 'updatedAt', 'summarizedEvents']:
        return int(val)
    elif key in ['isEphemeral', 'isUserEvent', 'canClose', 'canDelete']:
        return bool(val)
    else:
        raise ValueError('input arg of type {} is not in valid keys {}'.format(
            key, VALID_EVENT_DICT.keys()
        ))

EVENT_READONLY_FIELDS = ['id', 'isEphemeral', 'isUserEvent', 'runningState',
                         'canDelete', 'canClose', 'creatorType', 'createdAt',
                         'updatedAt', 'createdEpochMillis', 'updatedEpochMillis',
                         'updaterId', 'creatorId', 'summarizedEvents']

def _validate_body(ansible_module):
    params = ansible_module.params
    body = params['body']
    id = params.get('id', None)
    # annotations is required on create.
    if (not id) and (ansible_module.params.get('annotations', None) is None):
        # This is a create.  Fix up body a bit
        ansible_module.debug('adding empty annotations dict to body')
        body['annotations'] = {}
        if not body.get('startTime', None):
            body['startTime'] = params['validated_start_time']
        if not body.get('endTime', None):
            body['endTime'] = params['validated_end_time']
    else:
        # doing an update so don't try to change any readonly variables
        readonly = set(body.keys()).intersection(EVENT_READONLY_FIELDS)
        if readonly:
            ansible_module.fail_json(msg='''Invalid body for updating wf_event.
            {} are readonly.\n  All readonly vars are {}.\n
            Use annotations to insert blob into body
            eg. annotations.item = val'''.format(
                readonly,
                EVENT_READONLY_FIELDS,
            ))
        # by default update takes "<start_timestamp>:<event_name>" -> "0:<event_name>"
        # To update it maintaining the id, we must include id in body as well as url.
        body['id'] = id

    contained = set(body.keys()) - set(VALID_EVENT_DICT.keys())
    ansible_module.debug('_validate_body contained {}'.format(contained))
    if contained:
        ansible_module.fail_json(msg='''Invalid body for generating wf_event.
        {} are not in the set of valid keys {}
        Used annotations to insert blob debug into body
        eg. annotations.item = val'''.format(
            contained,
            VALID_EVENT_DICT.keys()
        ))
    invalid = {}
    new_body = deepcopy(body)
    for key, val in iteritems(body):
        if not isinstance(val, VALID_EVENT_DICT[key]):
            try:
                new_body[key] = safe_cast(key, val)
            except ValueError:
                invalid[key] = {'value': val,
                                'value_type': type(val),
                                'expected_type': VALID_EVENT_DICT[key]}
    if invalid:
        msg = ""
        for key, val in iteritems(invalid):
            msg += '''body item {} does not have the expected
                value type {}, for {}, instead it was {}.\n'''.format(
                    key, VALID_EVENT_DICT[key], val, type(val))
        msg += 'Please cast this into the correct type using jinja2.\n'
        raise ValueError(msg)

    return new_body



WF_EVENT_API = "/api/v2/event"
WF_SEARCH_EVENT_API = "/api/v2/search/event"

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


def to_millis(dtime):
    _epoch = datetime.datetime.utcfromtimestamp(0)
    return int((dtime - _epoch).total_seconds() * 1000)

def _read_response(response):
    try:
        return json.loads(response)
    except ValueError:
        return {}


def get_event_by_id(ansible_module):
    """
    gets the wavefront event and formats into something usable by ansible
    :param token:
    :param endpoint:
    :param id:
    :return:
    """
    ansible_module.debug('Getting wavefront event by id')
    params = ansible_module.params
    endpoint = params['endpoint']
    token = params['token']
    id = params['id']

    api_endpoint = '{}{}/{}'.format(endpoint, WF_EVENT_API, id)
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
                msg='Unable to query {} for id {}'.format(
                    api_endpoint,
                    id
                ),
                exception=str(url_error)
            )
    else:
        return _read_response(response.read())


def get_event_by_query(ansible_module):
    """
    gets the wavefront event and formats into something usable by ansible
    :param ansible_module: passes params from playbook to module
    :return: json dict of wf results
    """
    ansible_module.debug('Getting wavefront event by query')

    params = ansible_module.params
    endpoint = params['endpoint']
    token = params['token']
    query = params['query']

    api_endpoint = '{}{}'.format(endpoint, WF_SEARCH_EVENT_API)

    body = {
        "limit": int(params['limit']),
        "query": query,
        "timeRange": {
            "earliestStartTimeEpochMillis":  params['validated_start_time'],
            "latestStartTimeEpochMillis": params['validated_end_time']
        }
    }

    request = RequestWithMethod(
        api_endpoint,
        method='POST'
    )
    request.add_data(json.dumps(body))
    request.add_header('Content-Type', 'application/json')
    request.add_header('Authorization', 'Bearer {}'.format(token))

    try:
        response = urllib2.urlopen(request)
    except urllib2.HTTPError as url_error:
        """TODO handle 202 eg status": {
        "result": "OK",
        "message": "Your search reached the underlying limit of 250000 events scanned.
        Please consider shortening the time period used in your search.",
        "code": 202
        }, """

        body = _read_response(url_error.read())
        if body:
            message = body.get('status', {}).get('message', '')
            if message and 'does not exist' in message:
                return {}

            ansible_module.fail_json(
                msg='Unable to query {} for id {}'.format(
                    api_endpoint,
                    id
                ),
                exception=str(url_error)
            )
    else:
        return _read_response(response.read())

def generate_new_event(ansible_module):
    """
    Generates a new event into Wavefront
    """
    params = ansible_module.params
    body = params['body']
    token = params['token']
    endpoint = params['endpoint']
    api_endpoint = '{}{}'.format(endpoint, WF_EVENT_API)

    ansible_module.debug('Generating wavefront event')

    req = RequestWithMethod(
        api_endpoint,
        method='POST'
    )
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', 'Bearer {}'.format(token))
    print('request body - {}'.format(body))
    print('api_endpoint - {}'.format(api_endpoint))
    req.add_data(json.dumps(body))

    response = None
    for i in range(MAX_ATTEMPTS):
        ansible_module.debug('Creating wavefront event at {} with body {}'.format(
            req.get_full_url(), body))
        try:
            response = urllib2.urlopen(req)
            ansible_module.debug("event created ")
            break
        except urllib2.HTTPError as http_err:
            ansible_module.debug('Unable to create event in mon {}'.format(
                http_err.message
            ))
            if http_err.code == 406:
                ansible_module.warn('Wavefront may be rate limiting')
            elif http_err.code == 500:
                msg = 'http_err.msg {}'.format(http_err.msg) + \
                      'Server Error: {}'.format(http_err.message)
                ansible_module.fail_json(msg=msg)
            time.sleep(1 * (i + 1))

    else:
        ansible_module.debug('Rate limiter has likely been hit and the event will need ' \
              'to be manually cleaned after job execution ends.')

    try:
        return json.loads(response.read())
    except ValueError:
        raise Exception('There was an issue attempting to parse json returned.'
                        ' An event was still likely created, please cleanup'
                        'event manually via the UI.')


def get_times(ansible_module, start_time, end_time):
    """
    Convert valid input formats to standard
    :param ansible_module:
    :param start_time: in epoch time millis, datetime.datetime object or srtftime string in "%Y-%m-%dT%H:%M:%SZ"
    :param end_time:
    :return:
    """
    def get_time_millis(input_time):
        return int(input_time)

    try:
        valid_start_time = get_time_millis(start_time)
    except ValueError as err:
        msg = 'start_time {} of type {} should be timestamp in milliseconds\n{}'.format(
            start_time, type(start_time), err.message)
        ansible_module.fail_json(msg=msg)
    try:
        valid_end_time = get_time_millis(end_time)
    except ValueError as err:
        msg = 'end_time {} of type {} should be timestamp in milliseconds\n{}'.format(
            end_time, type(start_time), err)
        ansible_module.fail_json(msg=msg)

    if valid_start_time > valid_end_time:
        ansible_module.debug('Warning: start_time > end_time')
    return valid_start_time, valid_end_time

def update_event(ansible_module):
    """
    Updates a given event with the new body
    The following fields are readonly and will be ignored when passed in the request:
        id, isEphemeral, isUserEvent, runningState, canDelete, canClose,
        creatorType, createdAt, updatedAt, createdEpochMillis, updatedEpochMillis,
        updaterId, creatorId, and summarizedEvents
    """
    params = ansible_module.params
    id = params['id']
    body = params['body']
    token = params['token']
    endpoint = params['endpoint']

    req = RequestWithMethod('{}{}/{}'.format(endpoint, WF_EVENT_API, id),
                            method='PUT')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', 'Bearer {}'.format(token))
    req.add_data(json.dumps(body))

    response = None
    for i in range(MAX_ATTEMPTS):
        ansible_module.debug('Updating event')
        try:
            response = urllib2.urlopen(req)
            ansible_module.debug('Event updated')
            return json.loads(response.read())
        except urllib2.HTTPError as http_err:
            ansible_module.warn('Unable to update event, may be due to rate limiter {}'.format(
                http_err
            ))
            time.sleep(1 * (i + 1))

    ansible_module.fail_json(msg='Failed to update event')

def delete_event_by_id(ansible_module):
    """
    Delete a wavefront event
    :param ansible_module:
    :return: response
    """
    params = ansible_module.params
    id = params['id']
    body = params['body']
    token = params['token']
    endpoint = params['endpoint']

    req = RequestWithMethod('{}{}/{}'.format(endpoint, WF_EVENT_API, id),
                            method='DELETE')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', 'Bearer {}'.format(token))

    response = None
    for i in range(MAX_ATTEMPTS):
        ansible_module.debug('Deleting event')
        try:
            response = urllib2.urlopen(req)
            ansible_module.debug('Event deleted')
            return json.loads(response.read())
        except urllib2.HTTPError as http_err:
            ansible_module.warn('Unable to delete event\n{}'.format(
                http_err
            ))
            time.sleep(1 * (i + 1))

    ansible_module.fail_json(msg='Failed to delete event')

def main():

    ansible_module = AnsibleModule(argument_spec=dict(
        token=dict(required=True, default=None, no_log=True),
        endpoint=dict(default=None),
        id=dict(required=False, default=None),
        start_time=dict(default=to_millis(datetime.datetime.utcnow() - datetime.timedelta(hours=-1))),
        end_time=dict(default=to_millis(datetime.datetime.utcnow())),
        query=dict(default=None, type='list'),
        body=dict(default=None, type='dict'),
        delete=dict(default=False, type='bool'),
        limit=dict(default=10, type='int')
        ),
                                   mutually_exclusive=[
                                       ['query', 'body'],
                                       ['query', 'id']
                                   ]
                                  )

    params = ansible_module.params
    body = params['body']
    query = params['query']
    id = params['id']
    start_time = params['start_time']
    end_time = params['end_time']
    valid_start_time, valid_end_time = get_times(ansible_module, start_time, end_time)
    ansible_module.debug('Converted start_time {} to {}'.format(start_time, valid_start_time))
    ansible_module.debug('Converted end_time {} to {}'.format(end_time, valid_end_time))
    ansible_module.params['validated_start_time'] = valid_start_time
    ansible_module.params['validated_end_time'] = valid_end_time

    if body:
        # sanitize and prepare body
        ansible_module.debug('Provided body {}, \ntype {}'.format(body, type(body)))
        ansible_module.params['body'] = _validate_body(ansible_module)
        print('BODY {}'.format(ansible_module.params['body']))
        ansible_module.debug('Validated body {}, \ntype {}'.format(
            ansible_module.params['body'], type(body)))

    # Select which activity based on args
    if id:
        if body:
            # if id and body then update
            ansible_module.debug('Updating event {} with body {}'.format(
                id, ansible_module.params['body']))
            event_details = update_event(ansible_module)
            ansible_module.exit_json(
                changed=True,
                event=event_details.get('response', {}),
                request_body=ansible_module.params['body']
            )
        else:
            if params['delete']:
                ansible_module.debug('Deleting event by id {}'.format(id))
                event_details = delete_event_by_id(ansible_module)
                ansible_module.exit_json(
                    changed=True,
                    event=event_details.get('response', {})
                )
            else:
                # id only get event
                print("\n\n HERE \n\n")
                ansible_module.debug('Getting event by id {}'.format(id))
                event_details = get_event_by_id(ansible_module)
                ansible_module.exit_json(
                    changed=False,
                    event=event_details.get('response', {}),
                    request_body=ansible_module.params['body']
                )

    elif query:
        ansible_module.debug('Getting event by query {}'.format(query))
        event_details = get_event_by_query(ansible_module)
        ansible_module.exit_json(
            changed=False,
            event=event_details.get('response', {})
        )
    elif body:
        ansible_module.debug('Generating event with body {}'.format(ansible_module.params['body']))
        event_details = generate_new_event(ansible_module)
        ansible_module.exit_json(
            changed=True,
            event=event_details.get('response', {})
        )
    else:
        ansible_module.fail_json(msg='One of [id, query, body] module args is required')


if __name__ == '__main__':
    main()
